"""
카카오 모니터 통합 TC (T3) — 실제 SQLite + 최소 mock
"""
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session


# ---------------------------------------------------------------------------
# T3-01: OCR → diff → 키워드 매칭 파이프라인
# ---------------------------------------------------------------------------

def test_ocr_to_diff_to_keyword_pipeline():
    """T3: mock OCR 출력 → diff → 키워드 매칭 전체 파이프라인."""
    from app.modules.kakao_monitor.utils.text_diff import TextDiffDetector
    from unittest.mock import MagicMock

    # mock 키워드
    kw = MagicMock()
    kw.id = 1
    kw.keyword = "예약"
    kw.action_type = "collect"
    kw.is_active = True

    # 이전 → 현재 텍스트 변화 시뮬레이션
    prev_lines = ["홍길동: 안녕하세요", "김철수: 네"]
    curr_lines = ["홍길동: 안녕하세요", "김철수: 네", "홍길동: 예약 오픈했어요!"]

    diff_detector = TextDiffDetector()
    new_msgs = diff_detector.detect_new_messages(prev_lines, curr_lines)
    assert len(new_msgs) == 1
    assert "예약" in new_msgs[0]

    # 키워드 매칭
    import sys
    from unittest.mock import patch
    with patch.dict(sys.modules, {
        "psutil": MagicMock(), "win32gui": MagicMock(), "win32con": MagicMock(),
        "win32clipboard": MagicMock(), "pyautogui": MagicMock(),
        "paddleocr": MagicMock(), "imagehash": MagicMock(), "win32ui": MagicMock(),
    }):
        from app.worker.kakao_monitor_worker import KakaoMonitorWorker
        worker = KakaoMonitorWorker()
        matched = worker._match_keywords(new_msgs[0], [kw])
    assert matched is not None
    assert matched.keyword == "예약"


# ---------------------------------------------------------------------------
# T3-02: 수집 결과 → DB 저장 → 조회 파이프라인
# ---------------------------------------------------------------------------

def test_collect_and_save_pipeline(test_db_session: Session):
    """T3: 수집 결과 → DB 저장 → 조회 파이프라인."""
    from app.models.kakao_monitor import KakaoWatchConfig
    from app.modules.kakao_monitor.services.collect_service import KakaoCollectService

    cfg = KakaoWatchConfig(chat_name="파이프라인방", polling_interval_sec=3)
    test_db_session.add(cfg)
    test_db_session.commit()

    svc = KakaoCollectService(test_db_session)
    post = svc.save_collected_post(
        config_id=cfg.id,
        keyword_id=None,
        matched_keyword="공지",
        trigger_msg="공지 올라왔어요",
        content="전체 게시물 내용입니다.",
    )
    assert post.id is not None

    items, total = svc.get_collected_posts(config_id=cfg.id)
    assert total == 1
    assert items[0].matched_keyword == "공지"
    assert items[0].collected_content == "전체 게시물 내용입니다."


# ---------------------------------------------------------------------------
# T3-03: config → keyword → post → config 삭제 cascade
# ---------------------------------------------------------------------------

def test_config_with_keywords_and_posts_lifecycle(test_db_session: Session):
    """T3: config 생성 → keyword 추가 → post 저장 → config 삭제 cascade."""
    from app.models.kakao_monitor import (
        KakaoWatchConfig, KakaoKeyword, KakaoCollectedPost
    )

    cfg = KakaoWatchConfig(chat_name="라이프사이클방")
    test_db_session.add(cfg)
    test_db_session.flush()

    kw = KakaoKeyword(config_id=cfg.id, keyword="테스트")
    test_db_session.add(kw)
    test_db_session.flush()

    post = KakaoCollectedPost(
        config_id=cfg.id,
        keyword_id=kw.id,
        matched_keyword="테스트",
        trigger_message="트리거",
        collected_content="내용",
        status="success",
    )
    test_db_session.add(post)
    test_db_session.commit()

    kw_id = kw.id
    post_id = post.id

    # config 삭제 → cascade
    test_db_session.delete(cfg)
    test_db_session.commit()

    assert test_db_session.get(KakaoKeyword, kw_id) is None
    assert test_db_session.get(KakaoCollectedPost, post_id) is None


# ---------------------------------------------------------------------------
# T3-04: 실제 OCR 형태 텍스트 diff 검증
# ---------------------------------------------------------------------------

def test_text_diff_with_realistic_ocr_output():
    """T3: 실제 OCR 형태 텍스트 diff 검증."""
    from app.modules.kakao_monitor.utils.text_diff import TextDiffDetector

    prev = [
        "홍길동",
        "안녕하세요 오늘 일정 공유합니다",
        "김철수",
        "감사합니다",
    ]
    curr = [
        "홍길동",
        "안녕하세요 오늘 일정 공유합니다",
        "김철수",
        "감사합니다",
        "이순신",
        "예약 오픈 공지가 올라왔어요!",
    ]

    d = TextDiffDetector()
    new_msgs = d.detect_new_messages(prev, curr)
    assert "이순신" in new_msgs or "예약 오픈 공지가 올라왔어요!" in new_msgs


# ---------------------------------------------------------------------------
# T3-05: DB 마이그레이션 테이블 + 인덱스 존재 확인
# ---------------------------------------------------------------------------

def test_db_migration_tables_exist(test_db_session: Session):
    """T3: 실제 SQLite에 4개 테이블 존재 확인."""
    engine = test_db_session.bind
    conn = engine.raw_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cursor.fetchall()}
    conn.close()

    assert "kakao_watch_configs" in tables
    assert "kakao_keywords" in tables
    assert "kakao_collected_posts" in tables
    assert "kakao_alert_logs" in tables


def test_worker_uses_polling_interval_normalization():
    """T3: polling_interval_sec 정규화(최소 1초) 확인."""
    import sys

    with patch.dict(sys.modules, {
        "psutil": MagicMock(), "win32gui": MagicMock(), "win32con": MagicMock(),
        "win32clipboard": MagicMock(), "pyautogui": MagicMock(),
        "paddleocr": MagicMock(), "imagehash": MagicMock(), "win32ui": MagicMock(),
        "app.worker.crawl_worker_base": MagicMock(),
        "app.worker.scheduled_worker": MagicMock(),
        "app.worker.ondemand_worker": MagicMock(),
    }):
        from app.worker.kakao_monitor_worker import KakaoMonitorWorker

        worker = KakaoMonitorWorker()
        assert worker._normalize_interval(0) == 1.0
        assert worker._normalize_interval(0.5) == 1.0
        assert worker._normalize_interval(7) == 7.0


# ---------------------------------------------------------------------------
# T1-kakao-01: _monitor_chat() connection error → _log_worker_error 1회 + re-raise 없음
# ---------------------------------------------------------------------------

WIN32_MOCKS = {
    "psutil": MagicMock(), "win32gui": MagicMock(), "win32con": MagicMock(),
    "win32clipboard": MagicMock(), "pyautogui": MagicMock(),
    "paddleocr": MagicMock(), "imagehash": MagicMock(), "win32ui": MagicMock(),
    "app.worker.crawl_worker_base": MagicMock(),
    "app.worker.scheduled_worker": MagicMock(),
    "app.worker.ondemand_worker": MagicMock(),
}


def _make_kakao_worker():
    """win32 의존성 없이 KakaoMonitorWorker 생성."""
    with patch.dict("sys.modules", WIN32_MOCKS):
        from app.worker.kakao_monitor_worker import KakaoMonitorWorker
        return KakaoMonitorWorker()


@pytest.mark.asyncio
async def test_monitor_chat_connection_error_logs_without_traceback_integration():
    """T1: _monitor_chat() — _load_active_state()가 connection error 던질 때 _log_worker_error 1회 + raise 없음."""
    try:
        import psycopg2
    except ImportError:
        pytest.skip("psycopg2 없음")

    worker = _make_kakao_worker()
    worker._log_worker_error = MagicMock()

    conn_err = psycopg2.OperationalError("connection refused to server")
    worker._load_active_state = MagicMock(side_effect=conn_err)

    # _monitor_chat이 raise하지 않고 정상 return해야 함
    await worker._monitor_chat()

    worker._log_worker_error.assert_called_once_with("monitor_chat", conn_err)


@pytest.mark.asyncio
async def test_monitor_chat_non_connection_error_still_raises_error():
    """T1: _monitor_chat() — non-connection error는 기존처럼 raise 유지 (_safe_execute로 전파)."""
    worker = _make_kakao_worker()
    worker._log_worker_error = MagicMock()

    non_conn_err = RuntimeError("ocr capture failed")
    worker._load_active_state = MagicMock(side_effect=non_conn_err)

    with pytest.raises(RuntimeError, match="ocr capture failed"):
        await worker._monitor_chat()

    # connection error가 아니므로 _log_worker_error 호출 없음
    worker._log_worker_error.assert_not_called()
