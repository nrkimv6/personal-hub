"""네이버 브라우저 명령 처리 모듈.

NaverBrowserCommandHandler는 DB의 browser_commands 테이블에서 pending 명령을
조회·실행·결과 기록하는 책임만 가진다.
"""
import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import text

from app.database import SessionLocal

if TYPE_CHECKING:
    from app.shared.browser.browser_manager import BrowserManager

logger = logging.getLogger(__name__)


class NaverBrowserCommandHandler:
    """DB 브라우저 명령 큐 처리기.

    Args:
        browser_manager: 탭 획득에 사용하는 BrowserManager 인스턴스.
        worker_name: 로그 태그용 워커 이름.
    """

    def __init__(self, browser_manager: "BrowserManager", worker_name: str) -> None:
        self._browser = browser_manager
        self._worker_name = worker_name

    async def process_browser_commands(self) -> None:
        """대기 중인 브라우저 명령 처리."""
        if not self._browser:
            return

        db = SessionLocal()
        try:
            result = db.execute(text("""
                SELECT id, command_type, request_data, service_account_id
                FROM browser_commands
                WHERE status = 'pending'
                AND command_type IN ('open_browser', 'close_browser', 'naver_login', 'naver_check_login', 'check_login', 'coupang_login', 'instagram_login')
                ORDER BY created_at ASC
                LIMIT 5
            """))

            for row in result.mappings().all():
                command = {
                    "id": row["id"],
                    "command_type": row["command_type"],
                    "request_data": row["request_data"],
                    "service_account_id": row["service_account_id"],
                }

                try:
                    db.execute(text("""
                        UPDATE browser_commands
                        SET status = 'processing', started_at = :now
                        WHERE id = :id
                    """), {"now": datetime.now(), "id": command["id"]})
                    db.commit()

                    result_data = await self._execute_browser_command(command)

                    db.execute(text("""
                        UPDATE browser_commands
                        SET status = 'completed', result_data = :result,
                            completed_at = :now
                        WHERE id = :id
                    """), {
                        "result": str(result_data),
                        "now": datetime.now(),
                        "id": command["id"]
                    })
                    db.commit()

                except Exception as e:
                    logger.error(
                        f"[{self._worker_name}] 브라우저 명령 실패: {command['id']}, {e}"
                    )
                    db.execute(text("""
                        UPDATE browser_commands
                        SET status = 'failed', error_message = :error,
                            completed_at = :now
                        WHERE id = :id
                    """), {
                        "error": str(e),
                        "now": datetime.now(),
                        "id": command["id"]
                    })
                    db.commit()

        except Exception as e:
            logger.error(
                f"[{self._worker_name}] 브라우저 명령 처리 오류: {e}", exc_info=True
            )
            raise
        finally:
            db.close()

    async def _execute_browser_command(self, command: dict) -> dict:
        """브라우저 명령 실행."""
        cmd_type = command["command_type"]

        logger.info(f"[{self._worker_name}] 브라우저 명령 실행: {cmd_type}")

        if cmd_type == "open_browser":
            return await self._cmd_open_browser(command)
        elif cmd_type == "naver_login":
            return await self._cmd_naver_login(command)
        elif cmd_type in ("naver_check_login", "check_login"):
            # naver_check_login: 정식 명령. check_login: 레거시 하위 호환
            return await self._cmd_check_login(command)
        elif cmd_type == "close_browser":
            return await self._cmd_close_browser(command)
        elif cmd_type in ("coupang_login", "instagram_login"):
            # 쿠팡/인스타그램 로그인 페이지 열기 — open_browser와 동일 (URL은 request_data에 포함)
            return await self._cmd_open_browser(command)
        else:
            raise ValueError(f"알 수 없는 명령: {cmd_type}")

    async def _cmd_open_browser(self, command: dict) -> dict:
        """브라우저 열기 명령."""
        service_account_id = command.get("service_account_id")

        try:
            request_data = json.loads(command.get("request_data") or "{}")
            url = request_data.get("url", "https://naver.com")
        except Exception:
            url = "https://naver.com"

        async def _open(tab, **_):
            await tab.goto(url)

        await self._browser.execute_with_tab(
            callback=_open,
            service_account_id=service_account_id,
            target_id=command.get("id"),
            operation_timeout=30.0,
        )
        return {"status": "opened", "url": url}

    async def _cmd_naver_login(self, command: dict) -> dict:
        """네이버 로그인 페이지 열기."""
        service_account_id = command.get("service_account_id")
        url = "https://nid.naver.com/nidlogin.login"

        async def _login(tab, **_):
            await tab.goto(url)

        await self._browser.execute_with_tab(
            callback=_login,
            service_account_id=service_account_id,
            target_id=command.get("id"),
            operation_timeout=30.0,
        )
        return {"status": "login_page_opened"}

    async def _cmd_check_login(self, command: dict) -> dict:
        """로그인 상태 확인."""
        service_account_id = command.get("service_account_id")

        async def check_login_callback(tab) -> dict:
            await tab.goto("https://nid.naver.com/user2/help/myInfo")
            content = await tab.content()
            is_logged_in = "로그아웃" in content or "logout" in content.lower()
            return {"logged_in": is_logged_in}

        result = await self._browser.execute_with_tab(
            callback=check_login_callback,
            service_account_id=service_account_id
        )

        return result

    async def _cmd_close_browser(self, command: dict) -> dict:
        """브라우저 세션 종료."""
        service_account_id = command.get("service_account_id")

        if self._browser and self._browser.context_manager:
            await self._browser.context_manager.close_context(service_account_id)

        return {"status": "closed"}
