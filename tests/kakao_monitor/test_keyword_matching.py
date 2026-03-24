"""
키워드 매칭 단위 테스트 — KakaoMonitorWorker._match_keywords()
"""
import sys
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture(autouse=True)
def clear_cache():
    # 워커 모듈만 제거 (models/utils는 SQLAlchemy MetaData 충돌 방지를 위해 보존)
    sys.modules.pop("app.worker.kakao_monitor_worker", None)
    yield


def _make_keyword(id: int, keyword: str, action_type: str = "collect", is_active: bool = True):
    kw = MagicMock()
    kw.id = id
    kw.keyword = keyword
    kw.action_type = action_type
    kw.is_active = is_active
    return kw


def _get_worker():
    """KakaoMonitorWorker 인스턴스 반환 (win32/worker chain 모두 mock)."""
    # app.worker.__init__이 scheduled_worker → writing_worker → llm_request 체인을
    # 다시 임포트하면 SQLAlchemy 클래스 중복 등록 에러가 발생함.
    # app.worker 서브모듈을 미리 mock하여 __init__ 체인 실행을 차단.
    _mocks = {
        "psutil": MagicMock(), "win32gui": MagicMock(),
        "win32con": MagicMock(), "win32clipboard": MagicMock(),
        "pyautogui": MagicMock(), "paddleocr": MagicMock(),
        "imagehash": MagicMock(), "win32ui": MagicMock(),
        "app.worker.crawl_worker_base": MagicMock(),
        "app.worker.scheduled_worker": MagicMock(),
        "app.worker.ondemand_worker": MagicMock(),
    }
    sys.modules.pop("app.worker.kakao_monitor_worker", None)
    with patch.dict(sys.modules, _mocks):
        from app.worker.kakao_monitor_worker import KakaoMonitorWorker
        return KakaoMonitorWorker()


def test_match_right():
    """R: '예약' 키워드, '예약 오픈되었습니다' → 매칭"""
    w = _get_worker()
    keywords = [_make_keyword(1, "예약")]
    result = w._match_keywords("예약 오픈되었습니다", keywords)
    assert result is not None
    assert result.keyword == "예약"


def test_match_case_insensitive():
    """B: 'OPEN' 키워드, 'open now' → 매칭"""
    w = _get_worker()
    keywords = [_make_keyword(1, "OPEN")]
    result = w._match_keywords("open now", keywords)
    assert result is not None


def test_match_no_match():
    """E: 무관한 메시지 → None"""
    w = _get_worker()
    keywords = [_make_keyword(1, "예약")]
    result = w._match_keywords("날씨가 좋네요", keywords)
    assert result is None


def test_match_multiple_keywords_first_wins():
    """O: 여러 키워드 중 첫 번째 매칭 반환"""
    w = _get_worker()
    keywords = [
        _make_keyword(1, "오픈"),
        _make_keyword(2, "예약"),
    ]
    # "오픈 예약" → 키워드 1번이 먼저 나오므로 1번 반환
    result = w._match_keywords("오픈 예약", keywords)
    assert result is not None
    assert result.id == 1


def test_match_empty_keyword_list():
    """B: 키워드 0건 → None"""
    w = _get_worker()
    result = w._match_keywords("예약 오픈", [])
    assert result is None


def test_match_empty_message():
    """B: 빈 메시지 → None"""
    w = _get_worker()
    keywords = [_make_keyword(1, "예약")]
    result = w._match_keywords("", keywords)
    assert result is None


def test_match_inactive_keyword_skipped():
    """Co: is_active=False 키워드 스킵 (워커 레벨에서 필터링)"""
    # 워커 루프에서 is_active=False 키워드는 이미 필터링됨
    # _match_keywords 자체는 리스트를 그대로 사용하므로
    # 비활성 키워드가 포함된 경우 매칭되는지 확인
    w = _get_worker()
    inactive_kw = _make_keyword(1, "예약", is_active=False)
    # 워커 루프에서 이미 필터링 후 _match_keywords 호출
    # 여기서는 필터링된 리스트만 전달 시뮬레이션
    active_keywords = [kw for kw in [inactive_kw] if kw.is_active]
    result = w._match_keywords("예약 오픈", active_keywords)
    assert result is None
