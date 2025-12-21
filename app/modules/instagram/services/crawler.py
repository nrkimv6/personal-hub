"""Instagram Feed Crawler - Playwright 기반 피드 크롤링."""

import asyncio
import logging
import random
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any, Optional, Set, Callable, Awaitable

from playwright.async_api import Page, ElementHandle

logger = logging.getLogger("instagram.crawler")


@dataclass
class CrawlOptions:
    """크롤링 옵션."""
    max_posts: int = 20
    scroll_count: int = 3
    wait_after_more: float = 1.0  # 더보기 클릭 후 대기 (0.5 → 1.0초)
    wait_after_scroll: float = 2.0
    duplicate_stop_count: int = 5  # 연속 중복 N개 시 새로고침 트리거 (0이면 비활성화)
    max_refresh_count: int = 3  # 최대 새로고침 횟수 (중복/새 게시물 없음 통합)
    no_new_posts_refresh_threshold: int = 3  # N회 연속 새 게시물 없으면 새로고침
    duplicate_refresh_enabled: bool = True  # 연속 중복 시 새로고침 활성화 (False면 즉시 중단)
    # 스크롤 동작 설정
    scroll_behavior: str = "human"  # "human" | "fast"
    min_scroll_delay: float = 1.5  # 최소 스크롤 대기 (초)
    max_scroll_delay: float = 3.5  # 최대 스크롤 대기 (초)
    read_pause_probability: float = 0.3  # 읽는 척 멈출 확률 (30%)


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

    def __init__(self, page: Page, db_duplicate_checker=None):
        """
        Args:
            page: Playwright Page 객체 (Instagram 로그인 상태)
            db_duplicate_checker: DB 중복 체크 함수 (post_id -> bool)
        """
        self.page = page
        self.processed_urls: Set[str] = set()
        self._db_duplicate_checker = db_duplicate_checker

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

            // 광고 여부: "회원님을 위한 추천", "Sponsored" 등 텍스트 기반 판별
            const adIndicators = ['회원님을 위한 추천', 'Sponsored', 'スポンサー', '赞助内容'];
            const text = el.textContent || '';
            result.is_ad = adIndicators.some(indicator => text.includes(indicator));

            // 이미지: alt="Photo by" 우선, scontent URL 폴백
            // 프로필 이미지(s150x150, 44x44, 32x32 등 작은 크기) 제외
            const photoByImgs = Array.from(el.querySelectorAll('img'))
                .filter(img => {
                    const alt = (img.alt || '').toLowerCase();
                    return alt.startsWith('photo by') || alt.startsWith('photo shared by');
                });

            if (photoByImgs.length > 0) {
                result.images = photoByImgs.map(img => ({ src: img.src, alt: img.alt || '' }));
            } else {
                // 폴백: scontent URL 이미지 (프로필 이미지 제외)
                const scontentImgs = Array.from(el.querySelectorAll('img[src*="scontent"]'));
                result.images = scontentImgs
                    .filter(img => {
                        const src = img.src || '';
                        // 프로필 이미지 패턴 제외
                        return !src.includes('s150x150') &&
                               !src.includes('s44x44') &&
                               !src.includes('s32x32') &&
                               !src.includes('s64x64');
                    })
                    .map(img => ({ src: img.src, alt: img.alt || '' }));
            }

            // 더보기 버튼 확인
            const allSpans = Array.from(el.querySelectorAll('span'));
            result.has_more_button = allSpans.some(s => s.textContent.trim() === '더 보기');

            return result;
        }""")

    # 더보기 버튼 텍스트 (다국어 지원)
    MORE_BUTTON_TEXTS = ['더 보기', 'more', 'もっと見る', '顯示更多', '显示更多']

    async def _click_more_button(self, article: ElementHandle) -> bool:
        """더보기 버튼 클릭 (Playwright 네이티브 + 다국어 지원)."""
        try:
            # 다국어 더보기 버튼 찾기
            for text in self.MORE_BUTTON_TEXTS:
                # Playwright 네이티브 방식: query_selector로 찾고 클릭
                more_button = await article.query_selector(f'span:has-text("{text}")')

                if more_button:
                    # 요소가 보이는지 확인
                    is_visible = await more_button.is_visible()
                    if is_visible:
                        await more_button.click()
                        logger.debug(f"Clicked more button: '{text}'")
                        return True
                    else:
                        logger.debug(f"More button found but not visible: '{text}'")

            # 폴백: JavaScript evaluate 방식
            clicked = await article.evaluate("""(el) => {
                const moreTexts = ['더 보기', 'more', 'もっと見る', '顯示更多', '显示更多'];
                const allSpans = Array.from(el.querySelectorAll('span'));
                for (const text of moreTexts) {
                    const moreSpan = allSpans.find(s => s.textContent.trim() === text);
                    if (moreSpan) {
                        moreSpan.click();
                        return text;
                    }
                }
                return null;
            }""")

            if clicked:
                logger.debug(f"Clicked more button (fallback): '{clicked}'")
                return True

            return False
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

    async def _scroll_page(self, options: CrawlOptions = None) -> int:
        """페이지 스크롤 후 현재 article 수 반환.

        Args:
            options: 크롤링 옵션 (스크롤 동작 설정 포함)

        Returns:
            현재 DOM의 article 수
        """
        if options is None:
            options = CrawlOptions()

        if options.scroll_behavior == "human":
            await self._scroll_human_like(options)
        else:
            # 기존 빠른 스크롤
            await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(options.wait_after_scroll)

        articles = await self.page.query_selector_all("article")
        return len(articles)

    async def _scroll_human_like(self, options: CrawlOptions) -> None:
        """사람처럼 자연스럽게 스크롤.

        - 점진적 스크롤 (viewport 기반)
        - 랜덤 대기 시간
        - 가끔 읽는 척 멈춤
        - 가끔 약간 위로 스크롤
        """
        # 현재 뷰포트 높이와 스크롤 위치
        viewport_height = await self.page.evaluate("window.innerHeight")
        current_scroll = await self.page.evaluate("window.scrollY")

        # 1-2 화면 높이만큼 스크롤 (랜덤)
        scroll_distance = viewport_height * random.uniform(0.8, 1.5)
        target_scroll = current_scroll + scroll_distance

        # 부드러운 스크롤 애니메이션
        await self.page.evaluate(f"""
            window.scrollTo({{
                top: {target_scroll},
                behavior: 'smooth'
            }})
        """)

        # 랜덤 대기 (min_scroll_delay ~ max_scroll_delay)
        delay = random.uniform(options.min_scroll_delay, options.max_scroll_delay)
        await asyncio.sleep(delay)

        # 가끔 읽는 척 멈춤 (read_pause_probability 확률)
        if random.random() < options.read_pause_probability:
            pause_time = random.uniform(2.0, 4.0)
            logger.debug(f"Pausing to read for {pause_time:.1f}s")
            await asyncio.sleep(pause_time)

        # 가끔 약간 위로 스크롤 (20% 확률)
        if random.random() < 0.2:
            scroll_up = random.randint(50, 150)
            await self.page.evaluate(f"""
                window.scrollBy({{top: -{scroll_up}, behavior: 'smooth'}})
            """)
            await asyncio.sleep(0.3)

    async def _refresh_feed(self) -> bool:
        """피드 페이지 새로고침.

        Returns:
            성공 여부
        """
        try:
            await self.page.reload(wait_until="domcontentloaded")
            await asyncio.sleep(2.0)  # 페이지 로드 대기
            await self.page.wait_for_selector("article", timeout=10000)
            logger.debug("Feed refreshed successfully")
            return True
        except Exception as e:
            logger.warning(f"Failed to refresh feed: {e}")
            return False

    def _extract_post_id_from_url(self, url: Optional[str]) -> Optional[str]:
        """URL에서 게시물 ID 추출."""
        if not url:
            return None
        # https://www.instagram.com/p/ABC123/
        if "/p/" in url:
            parts = url.split("/p/")
            if len(parts) > 1:
                # 쿼리 파라미터 먼저 제거, 그 다음 trailing slash 제거
                post_id = parts[1].split("?")[0].rstrip("/")
                return post_id
        return None

    def _is_db_duplicate(self, post: PostData) -> bool:
        """DB에서 중복 체크."""
        if not self._db_duplicate_checker:
            return False
        post_id = self._extract_post_id_from_url(post.url)
        if not post_id:
            return False
        return self._db_duplicate_checker(post_id)

    async def crawl_feed(
        self,
        options: CrawlOptions = None,
        on_post_collected: Optional[Callable[[PostData], Awaitable[bool]]] = None,
    ) -> List[PostData]:
        """피드 크롤링 메인 함수.

        Args:
            options: 크롤링 옵션
            on_post_collected: 게시물 수집 시 호출되는 콜백 (즉시 저장용).
                              콜백이 True 반환하면 신규 저장, False면 중복.

        Returns:
            수집된 게시물 목록
        """
        if options is None:
            options = CrawlOptions()

        all_posts: List[PostData] = []
        self.processed_urls.clear()
        consecutive_duplicates = 0
        refresh_count = 0  # 새로고침 횟수 (초기 수집에서도 사용)
        stop_reason = "completed"  # 종료 사유 추적

        logger.info(f"Starting Instagram feed crawl (max_posts={options.max_posts}, duplicate_stop={options.duplicate_stop_count}, duplicate_refresh={options.duplicate_refresh_enabled}, realtime_save={on_post_collected is not None})")

        # 초기 게시물 수집
        articles = await self.page.query_selector_all("article")
        logger.debug(f"Found {len(articles)} initial articles")

        initial_stop = False
        for i, article in enumerate(articles):
            if len(all_posts) >= options.max_posts:
                stop_reason = "max_posts_reached"
                break

            # 연속 중복 체크: 새로고침 또는 중단
            if options.duplicate_stop_count > 0 and consecutive_duplicates >= options.duplicate_stop_count:
                if options.duplicate_refresh_enabled and refresh_count < options.max_refresh_count:
                    refresh_count += 1
                    logger.info(f"Refreshing due to {consecutive_duplicates} consecutive duplicates ({refresh_count}/{options.max_refresh_count})")
                    consecutive_duplicates = 0
                    await self._refresh_feed()
                    # 새로고침 후 초기 수집 재시작을 위해 break
                    initial_stop = True
                    break
                else:
                    reason = "max_refresh_after_duplicates" if refresh_count >= options.max_refresh_count else "duplicate_stop"
                    logger.info(f"Stopping: {consecutive_duplicates} consecutive DB duplicates (reason={reason})")
                    stop_reason = reason
                    initial_stop = True
                    break

            post = await self.extract_post(article, len(all_posts) + 1)

            # URL 중복 체크 (세션 내 중복)
            if post.url and post.url in self.processed_urls:
                logger.debug(f"Skipping session duplicate post: {post.url}")
                continue

            if post.url:
                self.processed_urls.add(post.url)

            # DB 중복 체크
            if self._is_db_duplicate(post):
                consecutive_duplicates += 1
                logger.debug(f"DB duplicate #{consecutive_duplicates}: {post.url}")
                continue
            else:
                consecutive_duplicates = 0

            all_posts.append(post)

            # 즉시 저장 콜백 호출
            if on_post_collected:
                try:
                    saved = await on_post_collected(post)
                    logger.debug(f"Extracted & saved post #{post.index}: {post.account} (saved={saved})")
                except Exception as e:
                    logger.error(f"Failed to save post #{post.index}: {e}")
            else:
                logger.debug(f"Extracted post #{post.index}: {post.account}")

        # 초기 수집에서 중단되지 않았다면 스크롤 진행
        # 스크롤하여 추가 게시물 로드
        # NOTE: Instagram은 가상화(virtualization)를 사용하므로 DOM에는 항상
        # 화면에 보이는 7-10개 article만 존재. 스크롤해도 이전 article은 DOM에서 제거됨.
        # 따라서 매번 모든 article을 순회하고 URL 중복 체크로 이미 처리한 것을 skip.
        no_new_posts_count = 0  # 연속으로 새 게시물이 없는 스크롤 횟수
        scroll_performed = 0  # 실제 수행된 스크롤 횟수

        if not initial_stop or (initial_stop and stop_reason == "completed"):
            for scroll in range(options.scroll_count):
                if len(all_posts) >= options.max_posts:
                    stop_reason = "max_posts_reached"
                    logger.info(f"Reached max_posts limit: {options.max_posts}")
                    break

                # 연속 중복 체크: 새로고침 또는 중단
                if options.duplicate_stop_count > 0 and consecutive_duplicates >= options.duplicate_stop_count:
                    if options.duplicate_refresh_enabled and refresh_count < options.max_refresh_count:
                        refresh_count += 1
                        logger.info(f"Refreshing due to {consecutive_duplicates} consecutive duplicates ({refresh_count}/{options.max_refresh_count})")
                        consecutive_duplicates = 0
                        await self._refresh_feed()
                        # 새로고침 후 계속 진행
                    else:
                        reason = "max_refresh_after_duplicates" if refresh_count >= options.max_refresh_count else "duplicate_stop"
                        logger.info(f"Stopping scroll: {consecutive_duplicates} consecutive DB duplicates (reason={reason})")
                        stop_reason = reason
                        break

                scroll_performed += 1
                logger.debug(f"Scroll {scroll + 1}/{options.scroll_count} (refreshed: {refresh_count})")
                posts_before_scroll = len(all_posts)

                await self._scroll_page(options)
                articles = await self.page.query_selector_all("article")

                logger.debug(f"Total articles in DOM: {len(articles)}, collected so far: {len(all_posts)}")

                # 모든 article 순회 (가상화로 인해 새 article이 어디에든 있을 수 있음)
                should_break = False
                for article in articles:
                    if len(all_posts) >= options.max_posts:
                        stop_reason = "max_posts_reached"
                        break

                    # 연속 중복 체크: 새로고침 또는 중단
                    if options.duplicate_stop_count > 0 and consecutive_duplicates >= options.duplicate_stop_count:
                        if options.duplicate_refresh_enabled and refresh_count < options.max_refresh_count:
                            refresh_count += 1
                            logger.info(f"Refreshing due to {consecutive_duplicates} consecutive duplicates ({refresh_count}/{options.max_refresh_count})")
                            consecutive_duplicates = 0
                            await self._refresh_feed()
                            should_break = True  # 현재 article 순회 중단하고 새 스크롤 시작
                            break
                        else:
                            reason = "max_refresh_after_duplicates" if refresh_count >= options.max_refresh_count else "duplicate_stop"
                            logger.info(f"Stopping: {consecutive_duplicates} consecutive DB duplicates (reason={reason})")
                            stop_reason = reason
                            should_break = True
                            break

                    post = await self.extract_post(article, len(all_posts) + 1)

                    # 세션 내 URL 중복 체크 - 이미 처리한 게시물 skip
                    if post.url and post.url in self.processed_urls:
                        continue

                    if post.url:
                        self.processed_urls.add(post.url)

                    # DB 중복 체크
                    if self._is_db_duplicate(post):
                        consecutive_duplicates += 1
                        logger.debug(f"DB duplicate #{consecutive_duplicates}: {post.url}")
                        continue
                    else:
                        consecutive_duplicates = 0

                    all_posts.append(post)

                    # 즉시 저장 콜백 호출
                    if on_post_collected:
                        try:
                            saved = await on_post_collected(post)
                            logger.debug(f"Scroll {scroll+1} - saved post #{post.index}: {post.account} (saved={saved})")
                        except Exception as e:
                            logger.error(f"Failed to save post #{post.index}: {e}")

                # 중단 조건 도달 시 스크롤 루프 종료
                if should_break and stop_reason != "completed":
                    break

                # 이번 스크롤에서 새 게시물이 없으면 카운트 증가
                if len(all_posts) == posts_before_scroll:
                    no_new_posts_count += 1
                    logger.debug(f"No new posts in this scroll (count: {no_new_posts_count})")

                    # N회 연속 새 게시물 없으면 새로고침 시도
                    if no_new_posts_count >= options.no_new_posts_refresh_threshold:
                        if refresh_count < options.max_refresh_count:
                            refresh_count += 1
                            no_new_posts_count = 0
                            logger.info(f"Refreshing page ({refresh_count}/{options.max_refresh_count}) - no new posts for {options.no_new_posts_refresh_threshold} scrolls")
                            await self._refresh_feed()
                        else:
                            stop_reason = "max_refresh_no_new_posts"
                            logger.info(f"Stopping: max refresh count ({options.max_refresh_count}) reached")
                            break
                else:
                    no_new_posts_count = 0

        # 스크롤 루프가 정상 종료된 경우
        if stop_reason == "completed" and scroll_performed >= options.scroll_count:
            stop_reason = "scroll_exhausted"

        logger.info(f"Crawl completed: {len(all_posts)} posts collected (stop_reason={stop_reason}, consecutive_duplicates={consecutive_duplicates}, refresh_count={refresh_count}, scroll_performed={scroll_performed})")
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

    async def check_login_status(self) -> bool:
        """로그인 상태 확인.

        Returns:
            로그인 되어 있으면 True
        """
        try:
            # 현재 URL 확인
            current_url = self.page.url

            # 로그인 페이지로 리다이렉트되었는지 확인
            if "/accounts/login" in current_url:
                logger.warning("Redirected to login page")
                return False

            # 로그인 버튼 존재 여부 확인
            login_button = await self.page.query_selector('a[href="/accounts/login/"]')
            if login_button:
                logger.warning("Login button found - not logged in")
                return False

            # 프로필 아이콘 확인 (로그인 시 나타남)
            profile_link = await self.page.query_selector('a[href*="/accounts/edit/"]')
            if profile_link:
                return True

            # article 요소가 있으면 피드가 로드된 것으로 간주
            articles = await self.page.query_selector_all("article")
            if len(articles) > 0:
                return True

            logger.warning("Could not determine login status")
            return False

        except Exception as e:
            logger.error(f"Failed to check login status: {e}")
            return False


class LoginRequiredError(Exception):
    """로그인이 필요한 경우 발생하는 예외."""
    pass
