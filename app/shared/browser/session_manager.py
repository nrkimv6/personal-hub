"""
계정별 브라우저 세션 관리 모듈

브라우저 열기, 로그인 상태 확인, 세션 종료 등을 담당합니다.
BrowserService에서 분리된 독립 모듈입니다.
"""

import asyncio
import logging
from pathlib import Path
from typing import Dict, Optional, TYPE_CHECKING

from app.core.database import SessionLocal

if TYPE_CHECKING:
    from .context_manager import ContextManager

logger = logging.getLogger(__name__)


class SessionManager:
    """계정별 브라우저 세션 관리자"""

    def __init__(self, context_manager: "ContextManager"):
        """
        SessionManager 초기화

        Args:
            context_manager: 브라우저 컨텍스트 관리자
        """
        self.context_manager = context_manager

    async def open_browser_for_account(
        self,
        service_account_id: int,
        url: Optional[str] = None
    ) -> Dict:
        """특정 계정의 브라우저를 열고 선택적으로 URL로 이동합니다.

        기존 컨텍스트가 있으면 재사용하고 창을 포커스합니다.
        프로필이 다른 프로세스에서 사용 중이면 에러를 반환합니다.
        """
        from app.shared.service_account.service_account_service import service_account_service

        db = SessionLocal()
        try:
            account = service_account_service.get_by_id(db, service_account_id)
            if not account:
                return {"success": False, "message": f"계정 {service_account_id}를 찾을 수 없습니다"}

            # 프로필 잠금 파일 확인 (다른 프로세스에서 사용 중인지)
            profile_path = Path(account.profile.profile_path)
            lock_file = profile_path / "Default" / "LOCK"
            if lock_file.exists():
                try:
                    with open(lock_file, 'r+b') as f:
                        pass
                except (PermissionError, OSError):
                    logger.info(f"계정 {service_account_id} 프로필이 이미 사용 중입니다 (Worker에서 실행 중)")
                    return {
                        "success": True,
                        "message": f"브라우저가 이미 열려있습니다. Worker에서 관리 중인 브라우저를 확인하세요.",
                        "service_account_id": service_account_id,
                        "account_name": account.profile.name,
                        "already_open": True
                    }

            # 기존 컨텍스트 확인
            existing_context = self.context_manager.browser_contexts.get(service_account_id)
            if existing_context:
                context_valid = False
                pages = []
                try:
                    pages = existing_context.pages
                    if pages:
                        page = pages[0]
                        try:
                            _ = page.url
                            context_valid = True
                        except Exception as e:
                            logger.warning(f"페이지 접근 실패 (service_account_id={service_account_id}): {e}")
                    else:
                        try:
                            browser = existing_context.browser
                            if browser and browser.is_connected():
                                context_valid = True
                            else:
                                logger.warning(f"브라우저 연결 끊김 (service_account_id={service_account_id})")
                        except Exception as e:
                            logger.warning(f"브라우저 연결 상태 확인 실패 (service_account_id={service_account_id}): {e}")
                except Exception as e:
                    logger.warning(f"브라우저 컨텍스트 유효성 검사 실패 (service_account_id={service_account_id}): {e}")

                if context_valid and pages:
                    page = pages[0]
                    try:
                        cdp = await page.context.new_cdp_session(page)
                        window_info = await cdp.send("Browser.getWindowForTarget")
                        window_id = window_info.get("windowId")
                        if window_id:
                            await cdp.send("Browser.setWindowBounds", {
                                "windowId": window_id,
                                "bounds": {
                                    "left": 560,
                                    "top": 240,
                                    "width": 1280,
                                    "height": 800,
                                    "windowState": "normal"
                                }
                            })
                        await page.bring_to_front()
                        logger.info(f"계정 {service_account_id} 기존 브라우저 창을 포커스했습니다")
                    except Exception as e:
                        logger.warning(f"창 포커스 실패, 새 탭으로 이동: {e}")

                    if url:
                        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                        logger.info(f"계정 {service_account_id} 브라우저가 {url}로 이동했습니다")

                    return {
                        "success": True,
                        "message": f"기존 브라우저 창을 포커스했습니다",
                        "service_account_id": service_account_id,
                        "account_name": account.profile.name,
                        "url": url or page.url
                    }
                else:
                    try:
                        del self.context_manager.browser_contexts[service_account_id]
                    except Exception:
                        pass
                    logger.info(f"계정 {service_account_id} 컨텍스트가 닫혀있어 새로 생성합니다")

            # 기존 컨텍스트가 없으면 새로 생성
            context = await self.context_manager._create_browser_context_visible(service_account_id)
            page = await context.new_page()

            if url:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                logger.info(f"계정 {service_account_id} 브라우저가 {url}로 이동했습니다")
            else:
                logger.info(f"계정 {service_account_id} 브라우저가 열렸습니다 (빈 페이지)")

            return {
                "success": True,
                "message": f"브라우저가 열렸습니다",
                "service_account_id": service_account_id,
                "account_name": account.profile.name,
                "url": url or "about:blank"
            }

        except Exception as e:
            logger.error(f"브라우저 열기 실패 (service_account_id={service_account_id}): {str(e)}")
            return {"success": False, "message": str(e)}
        finally:
            db.close()

    async def open_naver_login(self, service_account_id: int) -> Dict:
        """특정 계정의 브라우저를 열고 네이버 로그인 페이지로 이동합니다."""
        naver_login_url = "https://nid.naver.com/nidlogin.login"
        return await self.open_browser_for_account(service_account_id, naver_login_url)

    async def check_naver_login_status(self, service_account_id: int) -> Dict:
        """특정 계정의 네이버 로그인 상태를 확인합니다."""
        from app.shared.service_account.service_account_service import service_account_service

        db = SessionLocal()
        try:
            account = service_account_service.get_by_id(db, service_account_id)
            if not account:
                return {"success": False, "message": f"계정 {service_account_id}를 찾을 수 없습니다", "is_logged_in": False}

            context = await self.context_manager._create_browser_context_visible(service_account_id)
            page = await context.new_page()

            try:
                await page.goto("https://www.naver.com", wait_until="domcontentloaded", timeout=15000)
                await asyncio.sleep(1)

                is_logged_in = False
                page_content = await page.content()

                if "로그인" in page_content:
                    login_link = await page.query_selector('a[href*="nidlogin"]')
                    if login_link:
                        login_text = await login_link.inner_text()
                        if "로그인" in login_text:
                            is_logged_in = False
                        else:
                            is_logged_in = True
                    else:
                        is_logged_in = True
                else:
                    is_logged_in = True

                try:
                    user_selectors = [
                        '.MyView-module__my_area___QlLak',
                        '.MyView-module__link_name',
                        '#account',
                        '.gnb_my'
                    ]
                    for selector in user_selectors:
                        user_elem = await page.query_selector(selector)
                        if user_elem:
                            is_logged_in = True
                            break
                except:
                    pass

                service_account_service.update_login_status(db, service_account_id, is_logged_in)

                logger.info(f"계정 {service_account_id} 로그인 상태 확인: {'로그인됨' if is_logged_in else '로그아웃'}")

                return {
                    "success": True,
                    "service_account_id": service_account_id,
                    "account_name": account.profile.name,
                    "is_logged_in": is_logged_in,
                    "message": "로그인됨" if is_logged_in else "로그인 필요"
                }

            finally:
                try:
                    await asyncio.shield(page.close())
                except Exception as close_err:
                    logger.debug(f"[SessionManager] naver login check page close 실패 (무시): {close_err}")

        except Exception as e:
            logger.error(f"로그인 상태 확인 실패 (service_account_id={service_account_id}): {str(e)}")
            return {"success": False, "message": str(e), "is_logged_in": False}
        finally:
            db.close()

    async def check_instagram_login_status(self, service_account_id: int) -> Dict:
        """특정 계정의 Instagram 로그인 상태를 확인합니다."""
        from app.shared.service_account.service_account_service import service_account_service

        db = SessionLocal()
        try:
            account = service_account_service.get_by_id(db, service_account_id)
            if not account:
                return {"success": False, "message": f"계정 {service_account_id}를 찾을 수 없습니다", "is_logged_in": False}

            context = await self.context_manager._create_browser_context_visible(service_account_id)
            page = await context.new_page()

            try:
                await page.goto("https://www.instagram.com/", wait_until="domcontentloaded", timeout=15000)
                await asyncio.sleep(2)

                is_logged_in = False

                login_button = await page.query_selector('a[href="/accounts/login/"]')
                if login_button:
                    is_logged_in = False
                else:
                    profile_selectors = [
                        'a[href*="/direct/inbox/"]',
                        'svg[aria-label="홈"]',
                        'svg[aria-label="Home"]',
                        'a[role="link"][tabindex="0"]',
                    ]
                    for selector in profile_selectors:
                        elem = await page.query_selector(selector)
                        if elem:
                            is_logged_in = True
                            break

                    if not is_logged_in:
                        feed_elem = await page.query_selector('article')
                        if feed_elem:
                            is_logged_in = True

                service_account_service.update_login_status(db, service_account_id, is_logged_in)

                logger.info(f"계정 {service_account_id} Instagram 로그인 상태 확인: {'로그인됨' if is_logged_in else '로그아웃'}")

                return {
                    "success": True,
                    "service_account_id": service_account_id,
                    "account_name": account.profile.name,
                    "is_logged_in": is_logged_in,
                    "message": "로그인됨" if is_logged_in else "로그인 필요"
                }

            finally:
                try:
                    await asyncio.shield(page.close())
                except Exception as close_err:
                    logger.debug(f"[SessionManager] instagram login check page close 실패 (무시): {close_err}")

        except Exception as e:
            logger.error(f"Instagram 로그인 상태 확인 실패 (service_account_id={service_account_id}): {str(e)}")
            return {"success": False, "message": str(e), "is_logged_in": False}
        finally:
            db.close()

    async def close_browser_session(self, service_account_id: int) -> Dict:
        """특정 계정의 브라우저 세션을 종료합니다."""
        from app.shared.service_account.service_account_service import service_account_service

        db = SessionLocal()
        try:
            account = service_account_service.get_by_id(db, service_account_id)
            account_name = account.profile.name if account and account.profile else f"ID:{service_account_id}"

            if service_account_id not in self.context_manager.browser_contexts:
                return {
                    "success": True,
                    "message": f"열려있는 브라우저 세션이 없습니다",
                    "service_account_id": service_account_id,
                    "account_name": account_name
                }

            await self.context_manager.close_context(service_account_id)

            logger.info(f"계정 {service_account_id} 브라우저 세션 종료 완료")

            return {
                "success": True,
                "message": "브라우저 세션이 종료되었습니다",
                "service_account_id": service_account_id,
                "account_name": account_name
            }

        except Exception as e:
            logger.error(f"브라우저 세션 종료 실패 (service_account_id={service_account_id}): {str(e)}")
            return {"success": False, "message": str(e)}
        finally:
            db.close()

    def get_active_sessions(self) -> Dict:
        """현재 활성화된 브라우저 세션 목록을 반환합니다."""
        return {
            "active_sessions": list(self.context_manager.browser_contexts.keys()),
            "count": len(self.context_manager.browser_contexts)
        }
