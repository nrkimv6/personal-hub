"""Facebook Feed Crawler - Playwright 기반 피드 크롤러."""

import asyncio
import logging
import random
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any, Optional, Set, Callable, Awaitable

from playwright.async_api import Page, ElementHandle

from .url_parser import (
    parse_facebook_url,
    FacebookUrlType,
    ParsedFacebookUrl,
)

logger = logging.getLogger("facebook.crawler")


@dataclass
class CrawlOptions:
    """크롤링 옵션."""
    max_posts: int = 20
    scroll_count: int = 3
    wait_after_scroll: float = 2.5
    duplicate_stop_count: int = 5   # 연속 중복 N개면 갱신
    max_refresh_count: int = 3      # 최대 새로고침 횟수
    no_new_posts_refresh_threshold: int = 3  # N번 연속 새 게시물 없으면 새로고침
    duplicate_refresh_enabled: bool = True
    # 스크롤 동작 설정
    scroll_behavior: str = "human"  # "human" | "fast"
    min_scroll_delay: float = 2.0   # Facebook은 더 느리게 (IP 차단 방지)
    max_scroll_delay: float = 4.5
    read_pause_probability: float = 0.3


@dataclass
class FacebookPostData:
    """크롤링된 Facebook 게시물 데이터."""
    index: int
    account: Optional[str] = None
    datetime_str: Optional[str] = None
    display_time: Optional[str] = None
    url: Optional[str] = None
    post_id: Optional[str] = None
    caption: Optional[str] = None
    images: List[Dict[str, str]] = field(default_factory=list)
    post_type: str = "NORMAL"   # NORMAL, SPONSORED, SUGGESTED, SHARED, EVENT, LINK, LIVE, GROUP_POST
    # Facebook 특화
    reactions: Dict[str, int] = field(default_factory=dict)
    total_reactions: int = 0
    shares: int = 0
    comments: int = 0
    original_post_url: Optional[str] = None
    link_preview: Optional[Dict[str, str]] = None
    source_type: Optional[str] = None  # 'feed' | 'group' | 'page' | 'profile'
    group_id: Optional[str] = None
    group_name: Optional[str] = None
    page_id: Optional[str] = None
    page_name: Optional[str] = None


@dataclass
class CrawlResult:
    """크롤링 결과."""
    posts: List[FacebookPostData]
    stop_reason: str
    duplicate_count: int
    scroll_performed: int
    refresh_count: int
    config_snapshot: Dict[str, Any]


class FacebookCrawler:
    """Facebook 피드 크롤러.

    Playwright Page 객체를 사용하여 Facebook 피드에서
    게시물 정보를 수집합니다.
    """

    # Facebook 게시물 ID 패턴
    POST_ID_PATTERN = re.compile(r'/posts/(\d+)')
    PFBID_PATTERN = re.compile(r'pfbid([A-Za-z0-9]+)')

    def __init__(self, page: Page, db_duplicate_checker=None):
        """
        Args:
            page: Playwright Page 객체 (Facebook 로그인 상태)
            db_duplicate_checker: DB 중복 체크 함수 (post_id -> bool)
        """
        self.page = page
        self.processed_ids: Set[str] = set()
        self._db_duplicate_checker = db_duplicate_checker

    def _extract_post_id(self, url: str) -> Optional[str]:
        """URL에서 게시물 ID를 추출합니다."""
        if not url:
            return None
        # /posts/{id} 패턴
        m = self.POST_ID_PATTERN.search(url)
        if m:
            return m.group(1)
        # pfbid 패턴
        m = self.PFBID_PATTERN.search(url)
        if m:
            return m.group(0)
        return None

    async def _human_scroll(self, options: CrawlOptions):
        """사람처럼 자연스러운 스크롤 동작."""
        delay = random.uniform(options.min_scroll_delay, options.max_scroll_delay)

        # 읽는 척 멈춤
        if random.random() < options.read_pause_probability:
            pause = random.uniform(1.0, 3.0)
            logger.debug(f"읽기 멈춤: {pause:.1f}초")
            await asyncio.sleep(pause)

        # 스크롤 거리에 약간의 변화
        scroll_amount = random.randint(600, 900)
        await self.page.evaluate(f"window.scrollBy(0, {scroll_amount})")
        await asyncio.sleep(delay)

    async def extract_post(self, article: ElementHandle, index: int) -> Optional[FacebookPostData]:
        """단일 게시물에서 정보 추출.

        Args:
            article: div[role='feed'] 내 게시물 엘리먼트
            index: 게시물 인덱스

        Returns:
            추출된 게시물 데이터 또는 None
        """
        post = FacebookPostData(index=index)

        try:
            # 게시물 URL 추출 (a[href*='/posts/'] 또는 a[href*='pfbid'])
            url_elem = await article.query_selector(
                "a[href*='/posts/'], a[href*='pfbid'], a[href*='/permalink/']"
            )
            if url_elem:
                href = await url_elem.get_attribute("href")
                if href:
                    if href.startswith("/"):
                        href = "https://www.facebook.com" + href
                    post.url = href
                    post.post_id = self._extract_post_id(href)

            # 작성자 추출
            author_elem = await article.query_selector(
                "h2 a[href], h3 a[href], strong a[href]"
            )
            if author_elem:
                post.account = await author_elem.inner_text()

            # 본문(caption) 추출
            caption_selectors = [
                "div[data-ad-comet-preview='message']",
                "div[data-ad-preview='message']",
                "div[dir='auto'][style*='text-align']",
                "div.xdj266r",  # Facebook 내부 클래스 (변경 가능)
            ]
            for sel in caption_selectors:
                elem = await article.query_selector(sel)
                if elem:
                    post.caption = await elem.inner_text()
                    if post.caption:
                        break

            # 시간 추출
            time_elem = await article.query_selector("a[role='link'] abbr, span[id*='jsc_c']")
            if time_elem:
                post.display_time = await time_elem.inner_text()
                aria_label = await time_elem.get_attribute("aria-label")
                post.datetime_str = aria_label or post.display_time

            # 이미지 추출
            img_elems = await article.query_selector_all(
                "img[src*='scontent'], img[src*='fbcdn']"
            )
            for img in img_elems:
                src = await img.get_attribute("src")
                alt = await img.get_attribute("alt") or ""
                if src:
                    post.images.append({"src": src, "alt": alt})

            # 게시물 유형 판별
            post.post_type = await self._detect_post_type(article)

            # 반응(Reactions) 수 추출
            await self._extract_reactions(article, post)

            # 댓글/공유 수 추출
            await self._extract_engagement(article, post)

            # 소스 유형 설정 (피드에서 수집)
            post.source_type = "feed"

        except Exception as e:
            logger.warning(f"게시물 {index} 추출 오류: {e}")

        return post

    async def _detect_post_type(self, article: ElementHandle) -> str:
        """게시물 유형을 감지합니다."""
        try:
            # 스폰서 광고 감지
            sponsored_selectors = [
                "a[aria-label*='후원'], a[aria-label*='Sponsored']",
                "span:has-text('후원'), span:has-text('Sponsored')",
            ]
            for sel in sponsored_selectors:
                try:
                    elem = await article.query_selector(sel)
                    if elem:
                        return "SPONSORED"
                except Exception:
                    pass

            # 공유 게시물 감지
            shared_elem = await article.query_selector(
                "div[data-testid='post_chevron_button'], a[href*='share']"
            )
            if shared_elem:
                return "SHARED"

            # 라이브 감지
            live_elem = await article.query_selector(
                "span:has-text('LIVE'), span[aria-label*='라이브']"
            )
            if live_elem:
                return "LIVE"

            # 링크 미리보기 감지
            link_elem = await article.query_selector(
                "div[role='link'][tabindex='0'] div[class*='_']"
            )
            if link_elem:
                return "LINK"

        except Exception:
            pass

        return "NORMAL"

    async def _extract_reactions(self, article: ElementHandle, post: FacebookPostData):
        """반응(Reactions) 수를 추출합니다."""
        try:
            # 반응 버튼/카운트 추출 (다양한 셀렉터 시도)
            reaction_selectors = [
                "span[aria-label*='명이 반응'], span[aria-label*='reactions']",
                "div[aria-label*='좋아요'] span",
            ]
            for sel in reaction_selectors:
                elem = await article.query_selector(sel)
                if elem:
                    text = await elem.inner_text()
                    if text:
                        count = self._parse_count(text)
                        post.total_reactions = count
                        post.reactions = {"like": count}  # 상세 분류 불가 시 like로
                        break
        except Exception:
            pass

    async def _extract_engagement(self, article: ElementHandle, post: FacebookPostData):
        """댓글 수, 공유 수를 추출합니다."""
        try:
            # 댓글 수
            comment_selectors = [
                "span[aria-label*='댓글'], span[aria-label*='comment']",
            ]
            for sel in comment_selectors:
                elem = await article.query_selector(sel)
                if elem:
                    text = await elem.inner_text()
                    post.comments = self._parse_count(text)
                    break

            # 공유 수
            share_selectors = [
                "span[aria-label*='공유'], span[aria-label*='share']",
            ]
            for sel in share_selectors:
                elem = await article.query_selector(sel)
                if elem:
                    text = await elem.inner_text()
                    post.shares = self._parse_count(text)
                    break
        except Exception:
            pass

    def _parse_count(self, text: str) -> int:
        """숫자 문자열을 파싱합니다 ('1.2만' -> 12000)."""
        if not text:
            return 0
        text = text.strip().replace(",", "")
        try:
            if "만" in text:
                num = float(re.sub(r"[^0-9.]", "", text)) * 10000
                return int(num)
            if "천" in text:
                num = float(re.sub(r"[^0-9.]", "", text)) * 1000
                return int(num)
            return int(re.sub(r"[^0-9]", "", text) or "0")
        except Exception:
            return 0

    async def crawl_feed(
        self,
        url: str,
        options: Optional[CrawlOptions] = None,
        on_post_collected: Optional[Callable[[FacebookPostData], Awaitable[None]]] = None,
    ) -> CrawlResult:
        """Facebook 피드를 크롤링합니다.

        Args:
            url: 크롤링 대상 Facebook URL
            options: 크롤링 옵션
            on_post_collected: 게시물 수집 시 콜백 (저장 처리 등)

        Returns:
            크롤링 결과
        """
        if options is None:
            options = CrawlOptions()

        posts: List[FacebookPostData] = []
        consecutive_duplicates = 0
        scroll_count = 0
        refresh_count = 0
        stop_reason = "unknown"

        logger.info(f"Facebook 크롤링 시작: {url} (max_posts={options.max_posts})")

        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2.5)
        except Exception as e:
            logger.error(f"페이지 로드 실패: {e}")
            return CrawlResult(
                posts=[],
                stop_reason="page_load_error",
                duplicate_count=0,
                scroll_performed=0,
                refresh_count=0,
                config_snapshot=vars(options),
            )

        while len(posts) < options.max_posts and scroll_count < options.scroll_count * 10:
            # 게시물 수집
            article_selectors = [
                "div[role='feed'] > div",
                "div[data-pagelet*='FeedUnit']",
            ]
            articles = []
            for sel in article_selectors:
                articles = await self.page.query_selector_all(sel)
                if articles:
                    break

            new_in_scroll = 0
            for i, article in enumerate(articles):
                if len(posts) >= options.max_posts:
                    stop_reason = "max_posts_reached"
                    break

                post = await self.extract_post(article, len(posts))
                if not post or not post.post_id:
                    continue

                # 중복 체크
                if post.post_id in self.processed_ids:
                    consecutive_duplicates += 1
                    continue

                # DB 중복 체크
                if self._db_duplicate_checker:
                    is_dup = await self._db_duplicate_checker(post.post_id)
                    if is_dup:
                        consecutive_duplicates += 1
                        continue

                self.processed_ids.add(post.post_id)
                posts.append(post)
                new_in_scroll += 1
                consecutive_duplicates = 0

                if on_post_collected:
                    try:
                        await on_post_collected(post)
                    except Exception as e:
                        logger.warning(f"콜백 오류: {e}")

            # 중단 조건
            if len(posts) >= options.max_posts:
                stop_reason = "max_posts_reached"
                break

            if (
                options.duplicate_refresh_enabled
                and consecutive_duplicates >= options.duplicate_stop_count
            ):
                if refresh_count >= options.max_refresh_count:
                    stop_reason = "max_refresh_after_duplicates"
                    break
                logger.info(f"연속 중복 {consecutive_duplicates}개 → 새로고침 ({refresh_count + 1})")
                await self.page.reload(wait_until="domcontentloaded")
                await asyncio.sleep(3.0)
                refresh_count += 1
                consecutive_duplicates = 0
                continue

            # 스크롤
            await self._human_scroll(options)
            scroll_count += 1

        if stop_reason == "unknown":
            stop_reason = "scroll_limit"

        logger.info(
            f"크롤링 완료: {len(posts)}개 수집, 중단 사유={stop_reason}, "
            f"스크롤={scroll_count}, 새로고침={refresh_count}"
        )

        return CrawlResult(
            posts=posts,
            stop_reason=stop_reason,
            duplicate_count=consecutive_duplicates,
            scroll_performed=scroll_count,
            refresh_count=refresh_count,
            config_snapshot=vars(options),
        )
