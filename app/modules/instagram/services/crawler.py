"""Instagram Feed Crawler - Playwright 기반 피드 크롤링."""

import asyncio
import logging
import random
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any, Optional, Set, Callable, Awaitable

from playwright.async_api import Page, ElementHandle

from .url_parser import (
    parse_instagram_url,
    InstagramUrlType,
    ParsedInstagramUrl,
)

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
    is_ad: bool = False  # 하위호환성 유지 (post_type == 'SPONSORED')
    post_type: str = "NORMAL"  # 'NORMAL', 'SPONSORED', 'SUGGESTED'
    cta_url: Optional[str] = None  # 광고 CTA 링크 ("더 알아보기" 버튼)
    likes: Optional[int] = None
    comments: Optional[int] = None


@dataclass
class CrawlResult:
    """크롤링 결과 데이터.

    크롤링 완료 후 통계 및 상세 정보를 포함합니다.
    """
    posts: List[PostData]
    stop_reason: str  # 'max_posts_reached', 'duplicate_stop', 'max_refresh_after_duplicates', etc.
    duplicate_count: int  # 중단 시점의 연속 중복 개수
    scroll_performed: int  # 실제 수행된 스크롤 횟수
    refresh_count: int  # 새로고침 횟수
    config_snapshot: Dict[str, Any]  # 수집 시점의 설정값


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
            data.post_type = basic.get("post_type", "NORMAL")
            data.cta_url = basic.get("cta_url")
            data.likes = basic.get("likes")
            data.comments = basic.get("comments")

            # 본문 추출 (더보기 버튼 클릭 포함)
            # 클릭 전 본문 미리 추출
            caption_before = await self._extract_caption(article, data.account)
            len_before = len(caption_before) if caption_before else 0

            if basic.get("has_more_button"):
                clicked = await self._click_more_button(article)
                if clicked:
                    # 본문 길이가 늘어날 때까지 폴링 (최대 2초, 0.2초 간격)
                    caption_expanded = False
                    for poll in range(10):
                        await asyncio.sleep(0.2)
                        caption_after = await self._extract_caption(article, data.account)
                        len_after = len(caption_after) if caption_after else 0
                        if len_after > len_before:
                            data.caption = caption_after
                            caption_expanded = True
                            logger.debug(
                                f"Caption expanded: {len_before} -> {len_after} chars "
                                f"(+{len_after - len_before}, poll={poll + 1})"
                            )
                            break
                    if not caption_expanded:
                        # 타임아웃: 클릭 전 본문 사용
                        data.caption = caption_before
                        logger.warning(
                            f"Caption expansion timeout: stayed at {len_before} chars "
                            f"(account={data.account})"
                        )
                else:
                    # 클릭 실패: 클릭 전 본문 사용
                    data.caption = caption_before
                    logger.warning(f"Failed to click more button (account={data.account})")
            else:
                # 더보기 버튼 없음: 클릭 전 본문 그대로 사용
                data.caption = caption_before

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

            // 게시물 유형 판별: NORMAL, SPONSORED, SUGGESTED
            const text = el.textContent || '';

            // 광고 체크 (유료 프로모션) - "광고", "Sponsored"
            const sponsoredIndicators = ['광고', 'Sponsored', 'スポンサー', '赞助内容'];
            const isSponsored = sponsoredIndicators.some(indicator => text.includes(indicator));

            // 추천 체크 (알고리즘 추천) - "회원님을 위한 추천", "Suggested for you"
            const suggestedIndicators = ['회원님을 위한 추천', 'Suggested for you', 'おすすめ', '推荐'];
            const isSuggested = suggestedIndicators.some(indicator => text.includes(indicator));

            // 게시물 유형 결정 (광고가 추천보다 우선)
            if (isSponsored) {
                result.post_type = 'SPONSORED';
                result.is_ad = true;
            } else if (isSuggested) {
                result.post_type = 'SUGGESTED';
                result.is_ad = false;
            } else {
                result.post_type = 'NORMAL';
                result.is_ad = false;
            }

            // CTA 링크 추출 (광고만 해당) - "더 알아보기", "Learn More" 등
            result.cta_url = null;
            if (isSponsored) {
                const links = Array.from(el.querySelectorAll('a'));
                const ctaLink = links.find(link => {
                    const linkText = link.innerText.trim();
                    const ariaLabel = link.getAttribute('aria-label') || '';
                    return linkText.includes('더 알아보기') ||
                           linkText.includes('Learn More') ||
                           linkText.includes('자세히 보기') ||
                           linkText.includes('Shop now') ||
                           linkText.includes('지금 쇼핑하기') ||
                           ariaLabel.includes('더 알아보기');
                });
                result.cta_url = ctaLink ? ctaLink.href : null;
            }

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

            // 좋아요/댓글 수: 텍스트 패턴 우선, 숫자 폴백
            // 광고/추천 게시물에서도 작동하도록 "좋아요 N개", "댓글 N개" 패턴 먼저 시도
            const sections = el.querySelectorAll('section');
            let likesFound = false;
            let commentsFound = false;

            for (const section of sections) {
                const spans = section.querySelectorAll('span');
                for (const span of spans) {
                    const text = span.innerText;
                    // 좋아요 패턴: "좋아요 N개"
                    if (!likesFound) {
                        const likesMatch = text.match(/좋아요\s*(\d+)개/);
                        if (likesMatch) {
                            result.likes = parseInt(likesMatch[1]);
                            likesFound = true;
                        }
                    }
                    // 댓글 패턴: "댓글 N개"
                    if (!commentsFound) {
                        const commentsMatch = text.match(/댓글\s*(\d+)개/);
                        if (commentsMatch) {
                            result.comments = parseInt(commentsMatch[1]);
                            commentsFound = true;
                        }
                    }
                }
                if (likesFound && commentsFound) break;
            }

            // 폴백: 숫자만 추출 (기존 방식)
            if (!likesFound || !commentsFound) {
                const section = el.querySelector('section');
                if (section) {
                    const numberSpans = Array.from(section.querySelectorAll('span'));
                    const numbers = [];
                    for (const span of numberSpans) {
                        const text = span.textContent.trim();
                        if (/^\d+$/.test(text)) {
                            numbers.push(parseInt(text));
                        } else if (/^[\d,.]+[천만]?$/.test(text)) {
                            let num = parseFloat(text.replace(/,/g, ''));
                            if (text.includes('천')) num *= 1000;
                            if (text.includes('만')) num *= 10000;
                            numbers.push(Math.floor(num));
                        }
                    }
                    if (!likesFound && numbers[0]) result.likes = numbers[0];
                    if (!commentsFound && numbers[1]) result.comments = numbers[1];
                }
            }

            return result;
        }""")

    # 더보기 버튼 텍스트 (다국어 지원)
    MORE_BUTTON_TEXTS = ['더 보기', 'more', 'もっと見る', '顯示更多', '显示更多']

    async def _has_more_button(self, article: ElementHandle) -> bool:
        """더보기 버튼이 존재하는지 확인."""
        try:
            return await article.evaluate("""(el) => {
                const moreTexts = ['더 보기', 'more', 'もっと見る', '顯示更多', '显示更多'];
                const allSpans = Array.from(el.querySelectorAll('span'));
                return allSpans.some(s => moreTexts.includes(s.textContent.trim()));
            }""")
        except Exception:
            return False

    async def _click_more_button(self, article: ElementHandle) -> bool:
        """더보기 버튼 클릭 (정확한 텍스트 매칭)."""
        try:
            # JavaScript로 정확히 매칭되는 버튼 찾아서 클릭
            clicked = await article.evaluate("""(el) => {
                const moreTexts = ['더 보기', 'more', 'もっと見る', '顯示更多', '显示更多'];
                const allSpans = Array.from(el.querySelectorAll('span'));

                for (const text of moreTexts) {
                    // 정확히 텍스트가 일치하는 span 찾기
                    const moreSpan = allSpans.find(s => s.textContent.trim() === text);
                    if (moreSpan) {
                        // 클릭 가능한지 확인 (보이는 요소)
                        const rect = moreSpan.getBoundingClientRect();
                        if (rect.width > 0 && rect.height > 0) {
                            moreSpan.click();
                            return { clicked: true, text: text };
                        }
                    }
                }
                return { clicked: false, text: null };
            }""")

            if clicked and clicked.get("clicked"):
                logger.debug(f"Clicked more button: '{clicked.get('text')}'")
                return True

            # 폴백: Playwright 네이티브 클릭 (force 옵션)
            for text in self.MORE_BUTTON_TEXTS:
                # 정확한 텍스트 매칭을 위해 text= 셀렉터 사용
                more_button = await article.query_selector(f'span:text-is("{text}")')
                if more_button:
                    try:
                        await more_button.click(force=True)
                        logger.debug(f"Clicked more button (native): '{text}'")
                        return True
                    except Exception as e:
                        logger.debug(f"Native click failed for '{text}': {e}")

            logger.debug("No more button found to click")
            return False
        except Exception as e:
            logger.warning(f"Failed to click more button: {e}")
            return False

    async def _extract_caption(
        self,
        article: ElementHandle,
        account: Optional[str]
    ) -> Optional[str]:
        """본문 추출.

        1차: 해시태그 기반 추출 (innerText로 줄바꿈 유지)
        2차: 구조 기반 추출 ("저장" → 계정명 → "좋아요/댓글")
        3차 폴백: 가장 긴 span 텍스트 (광고/추천 게시물용)
        """
        try:
            return await article.evaluate("""(el, account) => {
                // 1차: 해시태그 기반 추출 (innerText로 줄바꿈 유지)
                // 댓글 영역(ul)에 있지 않은 해시태그만 사용
                const hashtagLinks = el.querySelectorAll('a[href*="/explore/tags/"]');
                if (hashtagLinks.length > 0) {
                    let captionHashtag = null;

                    for (const link of hashtagLinks) {
                        // ul 안에 있으면 댓글 영역이므로 스킵
                        if (link.closest('ul')) continue;
                        captionHashtag = link;
                        break;
                    }

                    if (captionHashtag) {
                        let currentElement = captionHashtag;

                        // 해시태그를 포함하는 span까지 올라가기
                        while (currentElement && currentElement.tagName !== 'SPAN') {
                            currentElement = currentElement.parentElement;
                        }

                        if (currentElement) {
                            const caption = currentElement.innerText;
                            if (caption && caption.length > 10) {
                                return caption;
                            }
                        }
                    }
                }

                // 2차: 구조 기반 추출 (account가 있을 때)
                if (account) {
                    const text = el.textContent;

                    // "저장" 이후 본문 영역 찾기
                    const saveIdx = text.indexOf('저장');
                    if (saveIdx !== -1) {
                        const afterSave = text.substring(saveIdx + 2);

                        // 계정명 이후부터 추출
                        const accountIdx = afterSave.indexOf(account);
                        if (accountIdx !== -1) {
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

                            const caption = endIdx === -1
                                ? afterAccount.trim().substring(0, 1000)
                                : afterAccount.substring(0, endIdx).trim();

                            // 유효한 본문이면 반환
                            if (caption && caption.length > 10) {
                                return caption;
                            }
                        }
                    }
                }

                // 3차 폴백: 가장 긴 span 텍스트 (광고/추천 게시물용)
                // 가이드 문서: 50자 이상이고, "팔로워" 등 메타 정보 제외
                const allSpans = Array.from(el.querySelectorAll('span'));
                let captionText = '';
                let maxLength = 0;

                for (const span of allSpans) {
                    const text = span.innerText;
                    if (text && text.length > maxLength && text.length > 50 && !text.includes('팔로워')) {
                        maxLength = text.length;
                        captionText = text;
                    }
                }

                return captionText || null;
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

    def _normalize_post_url(self, url: str) -> str:
        """게시물 URL 정규화 - 쿼리 파라미터와 trailing slash 제거.

        예) https://www.instagram.com/p/ABC123/?igsh=xxx -> https://www.instagram.com/p/ABC123
            https://www.instagram.com/p/ABC123/ -> https://www.instagram.com/p/ABC123
        """
        if not url:
            return url
        # 쿼리 파라미터 제거
        url = url.split("?")[0]
        # trailing slash 제거
        url = url.rstrip("/")
        return url

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
    ) -> CrawlResult:
        """피드 크롤링 메인 함수.

        Args:
            options: 크롤링 옵션
            on_post_collected: 게시물 수집 시 호출되는 콜백 (즉시 저장용).
                              콜백이 True 반환하면 신규 저장, False면 중복.

        Returns:
            CrawlResult: 크롤링 결과 (게시물 목록, 통계 정보)
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

                # 스크롤 전 article 수 저장 (새 article 로드 여부 판단용)
                articles_before_scroll = len(await self.page.query_selector_all("article"))

                await self._scroll_page(options)
                articles = await self.page.query_selector_all("article")

                logger.debug(f"Articles in DOM: {articles_before_scroll} -> {len(articles)}, collected: {len(all_posts)}")

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

                # 스크롤 후 DOM에 새 article이 로드되지 않았으면 카운트 증가
                # (중복 여부와 관계없이, 실제로 페이지가 더 로드되었는지 확인)
                if len(articles) == articles_before_scroll:
                    no_new_posts_count += 1
                    logger.debug(f"No new articles loaded in this scroll (count: {no_new_posts_count})")

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

        # 설정 스냅샷 생성
        config_snapshot = {
            "max_posts": options.max_posts,
            "scroll_count": options.scroll_count,
            "duplicate_stop_count": options.duplicate_stop_count,
            "max_refresh_count": options.max_refresh_count,
            "duplicate_refresh_enabled": options.duplicate_refresh_enabled,
            "no_new_posts_refresh_threshold": options.no_new_posts_refresh_threshold,
            "scroll_behavior": options.scroll_behavior,
        }

        logger.info(f"Crawl completed: {len(all_posts)} posts collected (stop_reason={stop_reason}, consecutive_duplicates={consecutive_duplicates}, refresh_count={refresh_count}, scroll_performed={scroll_performed})")

        return CrawlResult(
            posts=all_posts,
            stop_reason=stop_reason,
            duplicate_count=consecutive_duplicates,
            scroll_performed=scroll_performed,
            refresh_count=refresh_count,
            config_snapshot=config_snapshot,
        )

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


    async def _click_more_button_on_page(self) -> bool:
        """페이지 전체에서 더보기 버튼 클릭 (개별 게시물 페이지용)."""
        try:
            clicked = await self.page.evaluate("""() => {
                const moreTexts = ['더 보기', 'more', 'もっと見る', '顯示更多', '显示更多'];
                const allSpans = Array.from(document.querySelectorAll('span'));

                for (const text of moreTexts) {
                    const moreSpan = allSpans.find(s => s.textContent.trim() === text);
                    if (moreSpan) {
                        const rect = moreSpan.getBoundingClientRect();
                        if (rect.width > 0 && rect.height > 0) {
                            moreSpan.click();
                            return true;
                        }
                    }
                }
                return false;
            }""")

            if clicked:
                await asyncio.sleep(1.0)
            return clicked
        except Exception:
            return False

    async def _extract_single_post_data(self) -> Dict[str, Any]:
        """개별 게시물 페이지에서 데이터 추출 (가이드 문서 기반).

        Returns:
            추출된 데이터 딕셔너리
        """
        return await self.page.evaluate("""() => {
            const data = {};

            // 1. 작성자 - href에서 계정명 추출
            const links = Array.from(document.querySelectorAll('a[href^="/"]'));
            const accountLinks = links.filter(a => {
                const href = a.getAttribute('href');
                if (!href || href.includes('/explore/') || href.includes('/p/') || href.includes('/reel/')) return false;
                const path = href.split('?')[0];
                return path.match(/^\\/[a-z0-9_.]+\\/?$/);
            });
            if (accountLinks.length > 0) {
                const href = accountLinks[0].getAttribute('href');
                const path = href.split('?')[0];
                const match = path.match(/^\\/([^\\/]+)\\/?$/);
                data.account = match ? match[1] : null;
            }

            // 2. 게시 시간
            const timeElement = document.querySelector('time');
            if (timeElement) {
                data.datetime = timeElement.getAttribute('datetime');
                data.display_time = timeElement.innerText;
            }

            // 3. 좋아요 수 - "좋아요 N개" 패턴 매칭
            const allText = document.body.innerText || '';
            const likesMatch = allText.match(/좋아요\\s*([\\d,]+)개/);
            if (likesMatch) {
                data.likes = parseInt(likesMatch[1].replace(/,/g, ''));
            } else {
                // 영어 패턴: "N likes"
                const likesMatchEn = allText.match(/([\\d,]+)\\s*likes?/i);
                if (likesMatchEn) {
                    data.likes = parseInt(likesMatchEn[1].replace(/,/g, ''));
                }
            }

            // 4. 댓글 수 - "댓글 N개" 패턴 매칭
            const commentsMatch = allText.match(/댓글\\s*([\\d,]+)개/);
            if (commentsMatch) {
                data.comments = parseInt(commentsMatch[1].replace(/,/g, ''));
            } else {
                // 영어 패턴: "N comments" 또는 "View all N comments"
                const commentsMatchEn = allText.match(/(?:View all\\s+)?([\\d,]+)\\s*comments?/i);
                if (commentsMatchEn) {
                    data.comments = parseInt(commentsMatchEn[1].replace(/,/g, ''));
                }
            }

            // 5. 본문 - 가이드 문서 방식 (1순위: 해시태그 기반, 2순위: fallback)
            // 댓글 영역(ul)에 있지 않은 해시태그만 사용
            const hashtagLinks = document.querySelectorAll('a[href*="/explore/tags/"]');

            // 1순위: 해시태그 기반 방법 (가장 정확)
            if (hashtagLinks.length > 0) {
                let captionHashtag = null;

                for (const link of hashtagLinks) {
                    // ul 안에 있으면 댓글 영역이므로 스킵
                    if (link.closest('ul')) continue;
                    captionHashtag = link;
                    break;
                }

                if (captionHashtag) {
                    let currentElement = captionHashtag;

                    // 해시태그를 포함하는 span까지 올라가기
                    while (currentElement && currentElement.tagName !== 'SPAN') {
                        currentElement = currentElement.parentElement;
                    }

                    if (currentElement) {
                        data.caption = currentElement.innerText;
                    }
                }
            }

            // 2순위: 해시태그가 없는 경우 (대체 방법)
            if (!data.caption) {
                const main = document.querySelector('[role="main"]') || document.querySelector('article') || document.body;

                if (main) {
                    const spans = main.querySelectorAll('span');
                    let bestCaption = '';
                    let bestLength = 0;

                    const excludePatterns = [
                        'Afrikaans', 'Português', 'Deutsch', 'English', 'Español',
                        '답글', '팔로워', 'follower', '게시물', 'posts'
                    ];

                    for (const span of spans) {
                        const text = span.innerText || '';

                        // 최소 20자 이상
                        if (text.length < 20) continue;

                        // 제외 패턴 확인
                        const hasExcludePattern = excludePatterns.some(p => text.includes(p));
                        if (hasExcludePattern) continue;

                        // 가장 긴 텍스트 선택
                        if (text.length > bestLength) {
                            bestLength = text.length;
                            bestCaption = text;
                        }
                    }

                    // 작성자명/시간 제거
                    if (bestCaption) {
                        const lines = bestCaption.split('\\n');

                        // 첫 줄이 사용자명인지 확인
                        if (lines.length > 0 && lines[0].match(/^[a-z0-9._]+$/i)) {
                            let startIndex = 1;

                            // 빈 줄, "수정됨", "•", 시간 표시 건너뛰기
                            while (startIndex < lines.length) {
                                const line = lines[startIndex].trim();

                                if (line === '' ||
                                    line === '수정됨' ||
                                    line === '•' ||
                                    line.match(/^\\d+[년월주일시분초]$/) ||
                                    line.match(/^\\d+[mhdwy]$/i)) {
                                    startIndex++;
                                } else {
                                    break;
                                }
                            }

                            data.caption = lines.slice(startIndex).join('\\n').trim();
                        } else {
                            data.caption = bestCaption;
                        }
                    }
                }
            }

            // 6. 해시태그 (위에서 이미 hashtagLinks 조회함)
            data.hashtags = Array.from(hashtagLinks).map(link => link.innerText);

            // 7. 이미지 - cdninstagram 또는 scontent URL
            const postImages = document.querySelectorAll('img[src*="cdninstagram"], img[src*="scontent"]');
            data.images = Array.from(postImages)
                .filter(img => {
                    const src = img.src || '';
                    // 프로필 이미지 제외 (작은 크기)
                    return !src.includes('s150x150') &&
                           !src.includes('s44x44') &&
                           !src.includes('s32x32') &&
                           !src.includes('s64x64') &&
                           !src.includes('s320x320');
                })
                .map(img => ({ src: img.src, alt: img.alt || '' }));

            // 8. 비디오 확인
            const videos = document.querySelectorAll('video');
            data.hasVideo = videos.length > 0;
            if (data.hasVideo) {
                data.videoUrls = Array.from(videos).map(v => v.src).filter(s => s);
            }

            return data;
        }""")

    async def crawl_single_post(self, post_url: str) -> Optional[PostData]:
        """개별 게시물 URL로 직접 접근하여 정보 수집.

        Args:
            post_url: 게시물 URL (https://www.instagram.com/p/...)

        Returns:
            PostData | None: 수집된 게시물 데이터 또는 실패 시 None
        """
        try:
            # URL 정규화: 쿼리 파라미터와 trailing slash 제거
            post_url = self._normalize_post_url(post_url)
            logger.info(f"Crawling single post: {post_url}")

            # 게시물 페이지로 이동
            await self.page.goto(post_url, wait_until="domcontentloaded")

            # 페이지 로드 대기
            await asyncio.sleep(2.0)

            # 페이지 상태 확인
            body_text = await self.page.inner_text("body")

            # 로그인 필요 체크
            if "Log in" in body_text or "Log In" in body_text or "로그인" in body_text:
                logger.warning(f"Login required for: {post_url}")
                return None

            # 삭제/비공개 체크
            if "Sorry, this page isn't available" in body_text or "페이지를 사용할 수 없습니다" in body_text:
                logger.warning(f"Post unavailable: {post_url}")
                return None

            if "This Account is Private" in body_text or "비공개 계정" in body_text:
                logger.warning(f"Private account: {post_url}")
                return None

            # 더보기 버튼 클릭 (본문 확장)
            await self._click_more_button_on_page()

            # 개별 게시물 전용 추출 로직
            data = await self._extract_single_post_data()

            # PostData 객체 생성
            post = PostData(
                index=1,
                account=data.get("account"),
                datetime_str=data.get("datetime"),
                display_time=data.get("display_time"),
                url=post_url,
                caption=data.get("caption"),
                images=data.get("images", []),
                is_ad=False,
                likes=data.get("likes"),
                comments=data.get("comments"),
            )

            logger.info(f"Successfully crawled single post: {post.account}, likes={post.likes}, comments={post.comments}")
            return post

        except Exception as e:
            logger.error(f"Failed to crawl single post {post_url}: {e}")
            return None


class LoginRequiredError(Exception):
    """로그인이 필요한 경우 발생하는 예외."""
    pass


class NotSupportedError(Exception):
    """지원되지 않는 URL 타입 예외."""
    pass


@dataclass
class AccountCrawlResult:
    """계정/해시태그 크롤링 결과."""
    posts: List[PostData]
    total: int
    username: Optional[str] = None
    hashtag: Optional[str] = None
    is_private: bool = False
    error: Optional[str] = None


class InstagramUrlCrawler(InstagramCrawler):
    """URL 기반 Instagram 크롤러.

    다양한 Instagram URL 타입을 파싱하고 적절한 크롤링 메서드를 호출합니다.
    """

    async def crawl_url(
        self,
        url: str,
        options: CrawlOptions = None,
        on_post_collected: Optional[Callable[[PostData], Awaitable[bool]]] = None,
    ) -> AccountCrawlResult:
        """URL을 파싱하고 적절한 크롤링 메서드 호출.

        Args:
            url: Instagram URL
            options: 크롤링 옵션
            on_post_collected: 게시물 수집 시 호출되는 콜백

        Returns:
            AccountCrawlResult: 크롤링 결과

        Raises:
            NotSupportedError: 지원하지 않는 URL 타입
            ValueError: 잘못된 URL 형식
        """
        parsed = parse_instagram_url(url)
        options = options or CrawlOptions()

        match parsed.url_type:
            case InstagramUrlType.MAIN_FEED:
                result = await self.crawl_feed(options, on_post_collected)
                return AccountCrawlResult(
                    posts=result.posts,
                    total=len(result.posts),
                )

            case InstagramUrlType.ACCOUNT_PROFILE:
                return await self.crawl_account_feed(
                    parsed.username, options, on_post_collected
                )

            case InstagramUrlType.ACCOUNT_REELS:
                return await self.crawl_account_reels(
                    parsed.username, options, on_post_collected
                )

            case InstagramUrlType.SINGLE_POST:
                post = await self.crawl_single_post(url)
                return AccountCrawlResult(
                    posts=[post] if post else [],
                    total=1 if post else 0,
                )

            case InstagramUrlType.SINGLE_REEL:
                post = await self.crawl_single_post(url)
                return AccountCrawlResult(
                    posts=[post] if post else [],
                    total=1 if post else 0,
                )

            case InstagramUrlType.REELS_EXPLORE:
                return await self.crawl_reels_explore(options, on_post_collected)

            case InstagramUrlType.HASHTAG:
                return await self.crawl_hashtag(
                    parsed.hashtag, options, on_post_collected
                )

            case InstagramUrlType.STORY:
                raise NotSupportedError("스토리 크롤링은 지원되지 않습니다.")

            case _:
                raise ValueError(f"지원하지 않는 URL 형식: {url}")

    async def crawl_account_feed(
        self,
        username: str,
        options: CrawlOptions = None,
        on_post_collected: Optional[Callable[[PostData], Awaitable[bool]]] = None,
    ) -> AccountCrawlResult:
        """특정 계정의 게시물 피드 크롤링.

        Args:
            username: Instagram 사용자명
            options: 크롤링 옵션
            on_post_collected: 게시물 수집 시 호출되는 콜백

        Returns:
            AccountCrawlResult: 크롤링 결과
        """
        options = options or CrawlOptions()
        logger.info(f"Crawling account feed: @{username} (max_posts={options.max_posts})")

        try:
            # 프로필 페이지로 이동
            await self.page.goto(
                f"https://www.instagram.com/{username}/",
                wait_until="domcontentloaded"
            )
            await asyncio.sleep(2.0)

            # 비공개 계정 체크
            if await self._is_private_account():
                logger.warning(f"Account @{username} is private")
                return AccountCrawlResult(
                    posts=[],
                    total=0,
                    username=username,
                    is_private=True,
                    error="비공개 계정입니다.",
                )

            # 그리드에서 게시물 URL 수집
            post_urls = await self._extract_grid_post_urls(options.max_posts)
            logger.info(f"Found {len(post_urls)} post URLs from @{username}")

            # 각 게시물 상세 크롤링
            posts = []
            for i, post_url in enumerate(post_urls):
                post = await self.crawl_single_post(post_url)
                if post:
                    post.index = i + 1
                    posts.append(post)

                    # 콜백 호출
                    if on_post_collected:
                        try:
                            await on_post_collected(post)
                        except Exception as e:
                            logger.error(f"Failed to save post: {e}")

                    # Human-like 대기
                    await asyncio.sleep(random.uniform(1.0, 2.5))

            return AccountCrawlResult(
                posts=posts,
                total=len(posts),
                username=username,
            )

        except Exception as e:
            logger.error(f"Failed to crawl account @{username}: {e}")
            return AccountCrawlResult(
                posts=[],
                total=0,
                username=username,
                error=str(e),
            )

    async def crawl_account_reels(
        self,
        username: str,
        options: CrawlOptions = None,
        on_post_collected: Optional[Callable[[PostData], Awaitable[bool]]] = None,
    ) -> AccountCrawlResult:
        """특정 계정의 릴스 크롤링.

        Args:
            username: Instagram 사용자명
            options: 크롤링 옵션
            on_post_collected: 게시물 수집 시 호출되는 콜백

        Returns:
            AccountCrawlResult: 크롤링 결과
        """
        options = options or CrawlOptions()
        logger.info(f"Crawling account reels: @{username}/reels")

        try:
            # 릴스 페이지로 이동
            await self.page.goto(
                f"https://www.instagram.com/{username}/reels/",
                wait_until="domcontentloaded"
            )
            await asyncio.sleep(2.0)

            # 비공개 계정 체크
            if await self._is_private_account():
                return AccountCrawlResult(
                    posts=[],
                    total=0,
                    username=username,
                    is_private=True,
                    error="비공개 계정입니다.",
                )

            # 릴스 그리드에서 URL 수집 (/reel/ 패턴)
            post_urls = await self._extract_grid_post_urls(
                options.max_posts, url_pattern="/reel/"
            )
            logger.info(f"Found {len(post_urls)} reel URLs from @{username}")

            # 각 릴스 상세 크롤링
            posts = []
            for i, post_url in enumerate(post_urls):
                post = await self.crawl_single_post(post_url)
                if post:
                    post.index = i + 1
                    posts.append(post)

                    if on_post_collected:
                        try:
                            await on_post_collected(post)
                        except Exception as e:
                            logger.error(f"Failed to save reel: {e}")

                    await asyncio.sleep(random.uniform(1.0, 2.5))

            return AccountCrawlResult(
                posts=posts,
                total=len(posts),
                username=username,
            )

        except Exception as e:
            logger.error(f"Failed to crawl account reels @{username}: {e}")
            return AccountCrawlResult(
                posts=[],
                total=0,
                username=username,
                error=str(e),
            )

    async def crawl_reels_explore(
        self,
        options: CrawlOptions = None,
        on_post_collected: Optional[Callable[[PostData], Awaitable[bool]]] = None,
    ) -> AccountCrawlResult:
        """릴스 탐색 피드 크롤링.

        Args:
            options: 크롤링 옵션
            on_post_collected: 게시물 수집 시 호출되는 콜백

        Returns:
            AccountCrawlResult: 크롤링 결과
        """
        options = options or CrawlOptions()
        logger.info(f"Crawling reels explore feed (max_posts={options.max_posts})")

        try:
            await self.page.goto(
                "https://www.instagram.com/reels/",
                wait_until="domcontentloaded"
            )
            await asyncio.sleep(2.0)

            # 메인 피드와 유사한 방식으로 크롤링
            result = await self.crawl_feed(options, on_post_collected)

            return AccountCrawlResult(
                posts=result.posts,
                total=len(result.posts),
            )

        except Exception as e:
            logger.error(f"Failed to crawl reels explore: {e}")
            return AccountCrawlResult(
                posts=[],
                total=0,
                error=str(e),
            )

    async def crawl_hashtag(
        self,
        hashtag: str,
        options: CrawlOptions = None,
        on_post_collected: Optional[Callable[[PostData], Awaitable[bool]]] = None,
    ) -> AccountCrawlResult:
        """해시태그 피드 크롤링.

        Args:
            hashtag: 해시태그 (# 없이)
            options: 크롤링 옵션
            on_post_collected: 게시물 수집 시 호출되는 콜백

        Returns:
            AccountCrawlResult: 크롤링 결과
        """
        options = options or CrawlOptions()
        logger.info(f"Crawling hashtag: #{hashtag} (max_posts={options.max_posts})")

        try:
            await self.page.goto(
                f"https://www.instagram.com/explore/tags/{hashtag}/",
                wait_until="domcontentloaded"
            )
            await asyncio.sleep(2.0)

            # 그리드에서 게시물 URL 수집
            post_urls = await self._extract_grid_post_urls(options.max_posts)
            logger.info(f"Found {len(post_urls)} post URLs for #{hashtag}")

            # 각 게시물 상세 크롤링
            posts = []
            for i, post_url in enumerate(post_urls):
                post = await self.crawl_single_post(post_url)
                if post:
                    post.index = i + 1
                    posts.append(post)

                    if on_post_collected:
                        try:
                            await on_post_collected(post)
                        except Exception as e:
                            logger.error(f"Failed to save post: {e}")

                    await asyncio.sleep(random.uniform(1.0, 2.5))

            return AccountCrawlResult(
                posts=posts,
                total=len(posts),
                hashtag=hashtag,
            )

        except Exception as e:
            logger.error(f"Failed to crawl hashtag #{hashtag}: {e}")
            return AccountCrawlResult(
                posts=[],
                total=0,
                hashtag=hashtag,
                error=str(e),
            )

    async def _is_private_account(self) -> bool:
        """비공개 계정인지 확인.

        Returns:
            bool: 비공개 계정이면 True
        """
        try:
            # 비공개 계정 텍스트 확인 (한국어/영어)
            private_selectors = [
                "text='비공개 계정입니다'",
                "text='This account is private'",
                "text='This Account is Private'",
            ]

            for selector in private_selectors:
                element = await self.page.query_selector(selector)
                if element:
                    return True

            # 팔로우 버튼만 있고 게시물 그리드가 없는 경우도 체크
            grid = await self.page.query_selector("article")
            if not grid:
                # main 영역에서 비공개 관련 요소 탐색
                main = await self.page.query_selector("main")
                if main:
                    text = await main.inner_text()
                    if "비공개" in text or "private" in text.lower():
                        return True

            return False

        except Exception as e:
            logger.warning(f"Failed to check private status: {e}")
            return False

    async def _extract_grid_post_urls(
        self,
        limit: int = 50,
        url_pattern: str = "/p/",
    ) -> List[str]:
        """게시물 그리드에서 URL 목록 추출.

        Instagram 프로필/해시태그 페이지의 그리드에서 게시물 URL을 추출합니다.
        가상화(virtualization)를 고려하여 스크롤하면서 수집합니다.

        Args:
            limit: 최대 수집할 게시물 수
            url_pattern: URL에 포함되어야 하는 패턴 ("/p/" 또는 "/reel/")

        Returns:
            List[str]: 게시물 URL 목록
        """
        urls = []
        seen = set()
        scroll_count = 0
        max_scrolls = limit // 3 + 5  # 대략적인 스크롤 횟수 계산

        while len(urls) < limit and scroll_count < max_scrolls:
            # 현재 그리드의 링크들 추출
            # 프로필 그리드: main 내의 a[href*="/p/"] 또는 a[href*="/reel/"]
            links = await self.page.query_selector_all(f'main a[href*="{url_pattern}"]')

            for link in links:
                href = await link.get_attribute("href")
                if href:
                    # 절대 URL로 변환
                    if href.startswith("/"):
                        href = f"https://www.instagram.com{href}"
                    # URL 정규화: 쿼리 파라미터와 trailing slash 제거
                    href = self._normalize_post_url(href)
                    if href not in seen:
                        seen.add(href)
                        urls.append(href)

                    if len(urls) >= limit:
                        break

            if len(urls) >= limit:
                break

            # 스크롤하여 더 많은 게시물 로드
            prev_count = len(urls)
            await self.page.evaluate("window.scrollBy(0, window.innerHeight)")
            await asyncio.sleep(random.uniform(1.0, 2.0))
            scroll_count += 1

            # 새 URL이 추가되지 않으면 중단 (페이지 끝)
            new_links = await self.page.query_selector_all(f'main a[href*="{url_pattern}"]')
            if len(new_links) == len(links) and len(urls) == prev_count:
                logger.debug(f"No new posts found after scroll {scroll_count}")
                break

        return urls[:limit]
