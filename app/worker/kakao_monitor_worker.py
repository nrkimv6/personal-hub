"""카카오톡 모니터 워커.

감시 흐름(단일 경로):
1. 활성 설정 1건 로드(다중 활성 시 가장 오래된 1건 선택)
2. chat_name 기준으로 대상 창 확보
3. 채팅 영역 캡처 → OCR → 신규 메시지 diff
4. 키워드 매칭
5. direct collect(collect) 또는 alert-only 분기
6. DB 저장 + 알림 발행

`kakao:collect_queue` push-only 경로는 사용 중단(deprecated) 상태이며,
현재 워커는 direct collect 경로만 사용한다.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

from app.core.database import is_connection_error
from app.core.dependencies import get_db_session
from app.shared.worker.base_worker import BaseWorker
from app.models.kakao_monitor import (
    KakaoWatchConfig,
    KakaoKeyword,
    KakaoCollectedPost,
)
from app.modules.kakao_monitor.runtime_status import (
    mark_loop,
    mark_error,
    increment_counter,
)
from app.modules.kakao_monitor.services.collect_service import KakaoCollectService
from app.modules.kakao_monitor.services.alert_service import KakaoAlertService
from app.modules.kakao_monitor.utils.kakao_app import KakaoAppController
from app.modules.kakao_monitor.utils.capture import KakaoCaptureUtil
from app.modules.kakao_monitor.utils.ocr_engine import get_ocr_engine, KakaoOCREngine
from app.modules.kakao_monitor.utils.post_collector import KakaoPostCollector
from app.modules.kakao_monitor.utils.text_diff import TextDiffDetector

if TYPE_CHECKING:
    from app.shared.browser.browser_manager import BrowserManager

logger = logging.getLogger(__name__)

# Deprecated: queue consumer 미구현으로 push-only 경로는 중단됨
KAKAO_COLLECT_QUEUE = "kakao:collect_queue"


@dataclass(frozen=True)
class _ConfigSnapshot:
    id: int
    chat_name: str
    polling_interval_sec: int


@dataclass(frozen=True)
class _KeywordSnapshot:
    id: int
    keyword: str
    action_type: str


class KakaoMonitorWorker(BaseWorker):
    """카카오톡 채팅방 OCR 감시 워커."""

    LOOP_INTERVAL = 3.0  # 초
    MIN_LOOP_INTERVAL = 1.0
    TRIGGER_DEDUPE_SECONDS = 15.0

    def __init__(self, browser_manager: Optional["BrowserManager"] = None):
        super().__init__("kakao_monitor_worker", browser_manager)

        self._app_ctrl = KakaoAppController()
        self._capture = KakaoCaptureUtil()
        self._ocr: KakaoOCREngine = get_ocr_engine()
        self._diff_detector = TextDiffDetector()
        self._collector = KakaoPostCollector()

        # 상태
        self._hwnd: int | None = None
        self._prev_image: object = None
        self._prev_lines: list[str] = []
        self._loop_interval = self.LOOP_INTERVAL
        self._trigger_seen_at: dict[str, float] = {}

    # ------------------------------------------------------------------ #
    # BaseWorker 인터페이스
    # ------------------------------------------------------------------ #

    async def _initialize(self) -> None:
        logger.info("[KAKAO_BOOT] 초기화 시작")
        if not self._app_ctrl.is_running():
            logger.warning("[KAKAO_BOOT] 카카오톡 프로세스 미실행")
            mark_loop(
                active_config_count=0,
                active_keyword_count=0,
                loop_interval_sec=self._loop_interval,
                idle_reason="kakao process not running",
            )
            return

        self._hwnd = self._app_ctrl.find_main_window()
        if self._hwnd:
            logger.info("[KAKAO_BOOT] 카카오톡 창 핸들 확보: 0x%X", self._hwnd)
        else:
            logger.warning("[KAKAO_BOOT] 카카오톡 창 핸들 미탐지")

    async def _main_loop_iteration(self) -> None:
        await self._safe_execute("monitor_chat", self._monitor_chat)

    def _get_loop_interval(self) -> float:
        return self._loop_interval

    # ------------------------------------------------------------------ #
    # 모니터링 로직
    # ------------------------------------------------------------------ #

    async def _monitor_chat(self) -> None:
        """1사이클 감시 로직."""
        try:
            config, keywords, active_config_count = self._load_active_state()

            if config is None:
                logger.debug("[KAKAO_LOOP] idle(no active config)")
                mark_loop(
                    active_config_count=0,
                    active_keyword_count=0,
                    loop_interval_sec=self._loop_interval,
                    idle_reason="idle(no active config)",
                )
                return

            self._loop_interval = self._normalize_interval(config.polling_interval_sec)
            mark_loop(
                active_config_count=active_config_count,
                active_keyword_count=len(keywords),
                loop_interval_sec=self._loop_interval,
                idle_reason=None,
            )

            hwnd = self._resolve_hwnd(config.chat_name)
            if hwnd is None:
                mark_loop(
                    active_config_count=active_config_count,
                    active_keyword_count=len(keywords),
                    loop_interval_sec=self._loop_interval,
                    idle_reason="window not found",
                )
                logger.warning("[KAKAO_CAPTURE] 창 핸들 확보 실패 chat=%r", config.chat_name)
                return

            curr_image = self._capture.capture_chat_area(hwnd)
            if curr_image is None:
                increment_counter("capture_failures")
                logger.warning("[KAKAO_CAPTURE] 채팅 영역 캡처 실패 hwnd=0x%X", hwnd)
                return

            if not self._diff_detector.has_visual_change(self._prev_image, curr_image):
                self._prev_image = curr_image
                return

            blocks = self._ocr.recognize(curr_image)
            curr_lines = [b.text.strip() for b in blocks if b.text and b.text.strip()]
            if not curr_lines:
                increment_counter("ocr_failures")
                logger.debug("[KAKAO_OCR] 인식 텍스트 없음")
                self._prev_image = curr_image
                self._prev_lines = []
                return

            new_messages = self._diff_detector.detect_new_messages(
                self._prev_lines,
                curr_lines,
            )
            self._prev_image = curr_image
            self._prev_lines = curr_lines

            if not new_messages:
                increment_counter("keyword_miss_count")
                return

            bbox_lookup = {
                block.text.strip(): block.bbox
                for block in blocks
                if block.text and block.text.strip() and block.bbox
            }

            logger.debug("[KAKAO_OCR] 새 메시지 %d건: %s", len(new_messages), new_messages)

            matched_count = 0
            for message in new_messages:
                matched_kw = self._match_keywords(message, keywords)
                if matched_kw is None:
                    continue

                if self._is_duplicate_trigger(config.id, matched_kw.id, message):
                    logger.debug("[KAKAO_COLLECT] dedupe skip keyword=%r", matched_kw.keyword)
                    continue

                matched_count += 1
                await self._collect_and_alert(
                    config=config,
                    keyword=matched_kw,
                    trigger_message=message,
                    bbox=bbox_lookup.get(message.strip()),
                )

            if matched_count == 0:
                increment_counter("keyword_miss_count")

        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
            mark_error(err)
            if is_connection_error(exc):
                self._log_worker_error("monitor_chat", exc)
                return
            raise

    def _load_active_state(self) -> tuple[_ConfigSnapshot | None, list[_KeywordSnapshot], int]:
        """활성 설정/키워드 스냅샷을 로드한다."""
        with get_db_session() as db:
            active_configs = (
                db.query(KakaoWatchConfig)
                .filter(KakaoWatchConfig.is_active.is_(True))
                .order_by(KakaoWatchConfig.id.asc())
                .all()
            )

            active_count = len(active_configs)
            if active_count == 0:
                return None, [], 0

            if active_count > 1:
                logger.warning(
                    "[KAKAO_BOOT] 다중 활성 설정 감지(%d건) - id가 가장 작은 설정 1건만 사용",
                    active_count,
                )

            cfg = active_configs[0]
            config = _ConfigSnapshot(
                id=cfg.id,
                chat_name=(cfg.chat_name or "").strip(),
                polling_interval_sec=cfg.polling_interval_sec,
            )
            keywords = [
                _KeywordSnapshot(
                    id=kw.id,
                    keyword=(kw.keyword or "").strip(),
                    action_type=(kw.action_type or "collect").strip(),
                )
                for kw in cfg.keywords
                if kw.is_active and (kw.keyword or "").strip()
            ]
            return config, keywords, active_count

    def _resolve_hwnd(self, chat_name: str) -> int | None:
        """감시 대상 창 핸들을 반환한다."""
        if not self._app_ctrl.is_running():
            logger.warning("[KAKAO_CAPTURE] 프로세스 미실행")
            return None

        if chat_name:
            chat_hwnd = self._app_ctrl.find_window_by_title(chat_name)
            if chat_hwnd is not None:
                self._hwnd = chat_hwnd
                return chat_hwnd

            logger.info("[KAKAO_CAPTURE] chat_name 창 미탐지 - 진입 시도: %r", chat_name)
            if self._app_ctrl.navigate_to_chat(chat_name):
                chat_hwnd = self._app_ctrl.find_window_by_title(chat_name)
                if chat_hwnd is not None:
                    self._hwnd = chat_hwnd
                    return chat_hwnd

        if self._hwnd is not None:
            try:
                left, top, right, bottom = self._app_ctrl.get_window_rect(self._hwnd)
                if right > left and bottom > top:
                    return self._hwnd
            except Exception:
                pass

        self._hwnd = self._app_ctrl.find_main_window()
        return self._hwnd

    async def _collect_and_alert(
        self,
        *,
        config: _ConfigSnapshot,
        keyword: _KeywordSnapshot,
        trigger_message: str,
        bbox: tuple | None,
    ) -> None:
        """키워드 매칭 결과를 수집/저장/알림으로 처리한다."""
        action_type = self._normalize_action_type(keyword.action_type)

        status = KakaoCollectedPost.STATUS_PARTIAL
        collected_content = trigger_message

        if action_type == KakaoKeyword.ACTION_TYPE_COLLECT:
            collect_result = self._collect_post_content(bbox)
            if collect_result.success:
                status = KakaoCollectedPost.STATUS_SUCCESS
                if collect_result.content.strip():
                    collected_content = collect_result.content.strip()
            else:
                status = KakaoCollectedPost.STATUS_PARTIAL
                if collect_result.content and collect_result.content.strip():
                    collected_content = collect_result.content.strip()
                logger.warning(
                    "[KAKAO_COLLECT] direct collect 실패 keyword=%r error=%s",
                    keyword.keyword,
                    collect_result.error,
                )

        with get_db_session() as db:
            collect_service = KakaoCollectService(db)
            post = collect_service.save_collected_post(
                config_id=config.id,
                keyword_id=keyword.id,
                matched_keyword=keyword.keyword,
                trigger_msg=trigger_message,
                content=collected_content,
                status=status,
            )

            alert_service = KakaoAlertService(db)
            alert_service.send_alert(
                post,
                alert_type="sse",
                action_type=action_type,
            )

        logger.info(
            "[KAKAO_COLLECT] 처리 완료 config=%d keyword=%r action=%s status=%s",
            config.id,
            keyword.keyword,
            action_type,
            status,
        )

    def _collect_post_content(self, bbox: tuple | None):
        """post collector를 통한 direct collect를 실행한다."""
        if self._hwnd is None or bbox is None:
            from app.modules.kakao_monitor.utils.post_collector import CollectResult

            return CollectResult(success=False, error="missing hwnd or bbox")
        return self._collector.collect(self._hwnd, bbox)

    def _match_keywords(
        self,
        message: str,
        keywords: list[KakaoKeyword] | list[_KeywordSnapshot],
    ) -> _KeywordSnapshot | KakaoKeyword | None:
        """대소문자 무시 부분 매칭. 첫 번째 매칭 키워드 반환."""
        message_lower = message.lower()
        for kw in keywords:
            keyword_text = (kw.keyword or "").strip()
            if keyword_text and keyword_text.lower() in message_lower:
                logger.info("[KAKAO_MATCH] %r in %r", keyword_text, message)
                return kw
        return None

    def _normalize_interval(self, polling_interval_sec: int | float | None) -> float:
        """loop interval을 안전한 범위로 정규화한다."""
        if polling_interval_sec is None:
            return self.LOOP_INTERVAL
        try:
            value = float(polling_interval_sec)
        except Exception:
            return self.LOOP_INTERVAL
        return max(self.MIN_LOOP_INTERVAL, value)

    def _normalize_action_type(self, action_type: str) -> str:
        """action_type 유효값을 정규화한다."""
        candidate = (action_type or "").strip().lower()
        if candidate in {
            KakaoKeyword.ACTION_TYPE_COLLECT,
            KakaoKeyword.ACTION_TYPE_ALERT_ONLY,
        }:
            return candidate
        logger.warning(
            "[KAKAO_MATCH] 알 수 없는 action_type=%r - collect로 대체",
            action_type,
        )
        return KakaoKeyword.ACTION_TYPE_COLLECT

    def _is_duplicate_trigger(self, config_id: int, keyword_id: int, message: str) -> bool:
        """짧은 시간 동일 트리거의 재처리를 막는다."""
        key = f"{config_id}:{keyword_id}:{message.strip().lower()}"
        now = time.monotonic()
        last_seen = self._trigger_seen_at.get(key)
        if last_seen is not None and (now - last_seen) < self.TRIGGER_DEDUPE_SECONDS:
            return True

        self._trigger_seen_at[key] = now

        # 누적 키 정리
        expire_before = now - (self.TRIGGER_DEDUPE_SECONDS * 3)
        stale_keys = [k for k, seen_at in self._trigger_seen_at.items() if seen_at < expire_before]
        for stale_key in stale_keys:
            self._trigger_seen_at.pop(stale_key, None)
        return False
