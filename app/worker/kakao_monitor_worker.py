"""
카카오톡 모니터 워커 — BaseWorker 상속, 단일 채팅방 OCR 감시 루프.

감시 흐름:
    1. DB에서 활성 KakaoWatchConfig 1건 로드
    2. 채팅 영역 캡처
    3. 이미지 변경 감지 (phash)
    4. OCR 텍스트 추출
    5. 새 메시지 diff
    6. 키워드 매칭
    7. 매칭 시 Redis 큐에 수집 요청 push

v1: 단일 채팅방만 지원.
"""
from __future__ import annotations

import json
import logging
from typing import Optional, TYPE_CHECKING

from app.shared.worker.base_worker import BaseWorker
from app.modules.kakao_monitor.utils.kakao_app import KakaoAppController
from app.modules.kakao_monitor.utils.capture import KakaoCaptureUtil
from app.modules.kakao_monitor.utils.ocr_engine import get_ocr_engine, KakaoOCREngine
from app.modules.kakao_monitor.utils.text_diff import TextDiffDetector
from app.models.kakao_monitor import KakaoWatchConfig, KakaoKeyword

if TYPE_CHECKING:
    from app.shared.browser.browser_manager import BrowserManager

logger = logging.getLogger(__name__)

# Redis 큐 이름: 수집 요청
KAKAO_COLLECT_QUEUE = "kakao:collect_queue"


class KakaoMonitorWorker(BaseWorker):
    """카카오톡 채팅방 OCR 감시 워커."""

    LOOP_INTERVAL = 3.0  # 초

    def __init__(self, browser_manager: Optional["BrowserManager"] = None):
        super().__init__("kakao_monitor_worker", browser_manager)

        self._app_ctrl = KakaoAppController()
        self._capture = KakaoCaptureUtil()
        self._ocr: KakaoOCREngine = get_ocr_engine()
        self._diff_detector = TextDiffDetector()

        # 상태
        self._hwnd: int | None = None
        self._prev_image: object = None
        self._prev_lines: list[str] = []

    # ------------------------------------------------------------------ #
    # BaseWorker 인터페이스
    # ------------------------------------------------------------------ #

    async def _initialize(self) -> None:
        logger.info("[%s] 초기화 시작", self.name)
        if not self._app_ctrl.is_running():
            logger.warning("카카오톡 프로세스가 실행되지 않았습니다.")
        else:
            self._hwnd = self._app_ctrl.find_main_window()
            if self._hwnd:
                logger.info("카카오톡 창 핸들 확보: 0x%X", self._hwnd)
            else:
                logger.warning("카카오톡 창 핸들을 찾지 못했습니다.")

    async def _main_loop_iteration(self) -> None:
        await self._safe_execute("monitor_chat", self._monitor_chat)

    def _get_loop_interval(self) -> float:
        return self.LOOP_INTERVAL

    # ------------------------------------------------------------------ #
    # 모니터링 로직
    # ------------------------------------------------------------------ #

    async def _monitor_chat(self) -> None:
        """1사이클 감시 로직."""
        from app.database import get_db_session

        # 1. DB에서 활성 설정 로드 (v1: 1건)
        with get_db_session() as db:
            config: KakaoWatchConfig | None = (
                db.query(KakaoWatchConfig)
                .filter(KakaoWatchConfig.is_active.is_(True))
                .first()
            )
            if config is None:
                logger.debug("활성 감시 설정 없음 — 스킵")
                return

            config_id = config.id
            chat_name = config.chat_name
            keywords: list[KakaoKeyword] = [
                kw for kw in config.keywords if kw.is_active
            ]

        # 2. 창 핸들 갱신
        if self._hwnd is None or not self._app_ctrl.find_main_window():
            self._hwnd = self._app_ctrl.find_main_window()
            if self._hwnd is None:
                logger.warning("카카오톡 창 없음 — 스킵")
                return

        # 3. 채팅 영역 캡처
        curr_image = self._capture.capture_chat_area(self._hwnd)
        if curr_image is None:
            return

        # 4. 이미지 변경 감지
        if not self._diff_detector.has_visual_change(self._prev_image, curr_image):
            self._prev_image = curr_image
            return

        # 5. OCR 텍스트 추출
        curr_lines = self._ocr.get_text_lines(curr_image)

        # 6. 새 메시지 diff
        new_messages = self._diff_detector.detect_new_messages(
            self._prev_lines, curr_lines
        )
        self._prev_image = curr_image
        self._prev_lines = curr_lines

        if not new_messages:
            return

        logger.debug("새 메시지 %d건 감지: %s", len(new_messages), new_messages)

        # 7. 키워드 매칭 → Redis 큐 push
        for message in new_messages:
            matched_kw = self._match_keywords(message, keywords)
            if matched_kw is not None:
                await self._push_collect_request(
                    config_id=config_id,
                    chat_name=chat_name,
                    keyword_id=matched_kw.id,
                    matched_keyword=matched_kw.keyword,
                    trigger_message=message,
                    action_type=matched_kw.action_type,
                )

    def _match_keywords(
        self,
        message: str,
        keywords: list[KakaoKeyword],
    ) -> KakaoKeyword | None:
        """대소문자 무시 부분 매칭. 첫 번째 매칭 키워드 반환."""
        message_lower = message.lower()
        for kw in keywords:
            if kw.keyword.lower() in message_lower:
                logger.info("키워드 매칭: %r in %r", kw.keyword, message)
                return kw
        return None

    async def _push_collect_request(
        self,
        config_id: int,
        chat_name: str,
        keyword_id: int,
        matched_keyword: str,
        trigger_message: str,
        action_type: str,
    ) -> None:
        """Redis 큐에 수집 요청 push."""
        try:
            from app.shared.redis import get_redis_client
            redis_client = get_redis_client()
            if redis_client is None:
                logger.warning("Redis 클라이언트 없음 — 수집 요청 드롭")
                return

            payload = json.dumps(
                {
                    "config_id": config_id,
                    "chat_name": chat_name,
                    "keyword_id": keyword_id,
                    "matched_keyword": matched_keyword,
                    "trigger_message": trigger_message,
                    "action_type": action_type,
                },
                ensure_ascii=False,
            )
            await redis_client.rpush(KAKAO_COLLECT_QUEUE, payload)
            logger.info(
                "수집 요청 push: config=%d, keyword=%r, action=%s",
                config_id,
                matched_keyword,
                action_type,
            )
        except Exception as exc:
            logger.exception("Redis push 실패: %s", exc)
