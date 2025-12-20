"""Instagram Feed Crawler - Playwright 기반 피드 크롤링."""

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any, Optional, Set

from playwright.async_api import Page, ElementHandle

logger = logging.getLogger("instagram.crawler")


@dataclass
class CrawlOptions:
    """크롤링 옵션."""
    max_posts: int = 20
    scroll_count: int = 3
    wait_after_more: float = 0.5
    wait_after_scroll: float = 2.0


@dataclass
class PostData:
    """크롤링된 게시물 데이터."""
    index: int
    account: Optional[str] = None
    datetime_str: Optional[str] = None
    display_time: Optional[str] = None
    url: Optional[str] = None
    caption: Optional[str] = None
    images: List[Dict[str, str]] = field(default_factory=list)
    is_ad: bool = False


class InstagramCrawler:
    """Instagram 피드 크롤러.

    Playwright Page 객체를 사용하여 Instagram 피드에서
    게시물 정보를 수집합니다.
    """

    # 계정명 패턴: /username/ 또는 /username
    ACCOUNT_PATTERN = re.compile(r'^/([a-z0-9_.]+)/?$')

    def __init__(self, page: Page):
        """
        Args:
            page: Playwright Page 객체 (Instagram 로그인 상태)
        """
        self.page = page
        self.processed_urls: Set[str] = set()

    async def extract_post(self, article: ElementHandle, index: int) -> PostData:
        """단일 게시물에서 모든 정보 추출.

        Args:
            article: article 요소
            index: 게시물 인덱스

        Returns:
            추출된 게시물 데이터
        """
        data = PostData(index=index)

        try:
            # 기본 정보 추출
            basic = await self._extract_basic_info(article)
            data.account = basic.get("account")
            data.datetime_str = basic.get("datetime")
            data.display_time = basic.get("display_time")
            data.url = basic.get("url")
            data.images = basic.get("images", [])
            data.is_ad = basic.get("is_ad", False)

            # 더보기 버튼 클릭 (있으면)
            if basic.get("has_more_button"):
                await self._click_more_button(article)
                await asyncio.sleep(CrawlOptions().wait_after_more)

            # 본문 추출
            data.caption = await self._extract_caption(article, data.account)

        except Exception as e:
            logger.error(f"Failed to extract post #{index}: {e}")

        return data

    async def _extract_basic_info(self, article: ElementHandle) -> Dict[str, Any]:
        """게시물 기본 정보 추출."""
        return await article.evaluate("""(el) => {
            const result = {};

            // 계정명: /계정명/ 형태의 링크에서 추출
            const links = Array.from(el.querySelectorAll('a[href^="/"]'));
            const accountLinks = links.filter(a => {
                const href = a.getAttribute('href');
                if (!href || href.includes('/explore/') || href.includes('/p/')) return false;
                const path = href.split('?')[0];
                return path.match(/^\\/[a-z0-9_.]+\\/?$/);
            });

            if (accountLinks.length > 0) {
                const href = accountLinks[0].getAttribute('href');
                const path = href.split('?')[0];
                const match = path.match(/^\\/([^\\/]+)\\/?$/);
                result.account = match ? match[1] : null;
            }

            // 시간: time 태그
            const time = el.querySelector('time');
            if (time) {
                result.datetime = time.getAttribute('datetime');
                result.display_time = time.textContent.trim();
            }

            // URL: /p/ 포함 링크
            const postLink = el.querySelector('a[href*="/p/"]');
            if (postLink) {
                const href = postLink.getAttribute('href');
                result.url = 'https://www.instagram.com' + href.split('?')[0];
            }

            // 광고 여부: time이나 postLink 없으면 광고로 추정
            result.is_ad = !time || !postLink;

            // 이미지: scontent URL, 프로필 이미지(s150x150) 제외
            const imgs = Array.from(el.querySelectorAll('img[src*="scontent"]'));
            result.images = imgs
                .filter(img => !img.src.includes('s150x150'))
                .map(img => ({ src: img.src, alt: img.alt || '' }));

            // 더보기 버튼 확인
            const allSpans = Array.from(el.querySelectorAll('span'));
            result.has_more_button = allSpans.some(s => s.textContent.trim() === '더 보기');

            return result;
        }""")

    async def _click_more_button(self, article: ElementHandle) -> bool:
        """더보기 버튼 클릭."""
        try:
            clicked = await article.evaluate("""(el) => {
                const allSpans = Array.from(el.querySelectorAll('span'));
                const moreSpan = allSpans.find(s => s.textContent.trim() === '더 보기');
                if (moreSpan) {
                    moreSpan.click();
                    return true;
                }
                return false;
            }""")
            return clicked
        except Exception as e:
            logger.warning(f"Failed to click more button: {e}")
            return False

    async def _extract_caption(
        self,
        article: ElementHandle,
        account: Optional[str]
    ) -> Optional[str]:
        """본문 추출."""
        if not account:
            return None

        try:
            return await article.evaluate("""(el, account) => {
                if (!account) return null;

                const text = el.textContent;

                // "저장" 이후 본문 영역 찾기
                const saveIdx = text.indexOf('저장');
                if (saveIdx === -1) return null;

                const afterSave = text.substring(saveIdx + 2);

                // 계정명 이후부터 추출
                const accountIdx = afterSave.indexOf(account);
                if (accountIdx === -1) return null;

                const afterAccount = afterSave.substring(accountIdx + account.length);

                // "좋아요" 또는 "댓글"까지의 본문
                const endPatterns = ['좋아요', '댓글', 'Like', 'Comment'];
                let endIdx = -1;

                for (const pattern of endPatterns) {
                    const idx = afterAccount.indexOf(pattern);
                    if (idx !== -1 && (endIdx === -1 || idx < endIdx)) {
                        endIdx = idx;
                    }
                }

                if (endIdx === -1) {
                    return afterAccount.trim().substring(0, 1000);
                }

                return afterAccount.substring(0, endIdx).trim();
            }""", account)
        except Exception as e:
            logger.warning(f"Failed to extract caption: {e}")
            return None

    async def _scroll_page(self) -> int:
        """페이지 스크롤 후 현재 article 수 반환."""
        await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(CrawlOptions().wait_after_scroll)

        articles = await self.page.query_selector_all("article")
        return len(articles)

    async def crawl_feed(self, options: CrawlOptions = None) -> List[PostData]:
        """피드 크롤링 메인 함수.

        Args:
            options: 크롤링 옵션

        Returns:
            수집된 게시물 목록
        """
        if options is None:
            options = CrawlOptions()

        all_posts: List[PostData] = []
        self.processed_urls.clear()

        logger.info(f"Starting Instagram feed crawl (max_posts={options.max_posts})")

        # 초기 게시물 수집
        articles = await self.page.query_selector_all("article")
        logger.debug(f"Found {len(articles)} initial articles")

        for i, article in enumerate(articles):
            if len(all_posts) >= options.max_posts:
                break

            post = await self.extract_post(article, len(all_posts) + 1)

            # URL 중복 체크
            if post.url and post.url in self.processed_urls:
                logger.debug(f"Skipping duplicate post: {post.url}")
                continue

            if post.url:
                self.processed_urls.add(post.url)

            all_posts.append(post)
            logger.debug(f"Extracted post #{post.index}: {post.account}")

        # 스크롤하여 추가 게시물 로드
        for scroll in range(options.scroll_count):
            if len(all_posts) >= options.max_posts:
                break

            logger.debug(f"Scroll {scroll + 1}/{options.scroll_count}")
            prev_count = len(all_posts)

            new_article_count = await self._scroll_page()
            articles = await self.page.query_selector_all("article")

            logger.debug(f"Total articles after scroll: {len(articles)}")

            # 새로 로드된 게시물만 처리
            for i in range(prev_count, len(articles)):
                if len(all_posts) >= options.max_posts:
                    break

                post = await self.extract_post(articles[i], len(all_posts) + 1)

                if post.url and post.url in self.processed_urls:
                    continue

                if post.url:
                    self.processed_urls.add(post.url)

                all_posts.append(post)

        logger.info(f"Crawl completed: {len(all_posts)} posts collected")
        return all_posts

    async def navigate_to_feed(self) -> bool:
        """Instagram 피드로 이동.

        Returns:
            성공 여부
        """
        try:
            await self.page.goto("https://www.instagram.com/", wait_until="networkidle")

            # 피드 로드 확인
            await self.page.wait_for_selector("article", timeout=10000)
            return True
        except Exception as e:
            logger.error(f"Failed to navigate to feed: {e}")
            return False
