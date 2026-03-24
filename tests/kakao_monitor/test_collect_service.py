"""
KakaoCollectService 단위 테스트
"""
import os
import tempfile
from pathlib import Path
from datetime import datetime

import pytest
from sqlalchemy.orm import Session


@pytest.fixture
def svc(test_db_session: Session):
    from app.modules.kakao_monitor.services.collect_service import KakaoCollectService
    return KakaoCollectService(test_db_session)


@pytest.fixture
def config_id(test_db_session: Session):
    from app.models.kakao_monitor import KakaoWatchConfig
    cfg = KakaoWatchConfig(chat_name="테스트방", polling_interval_sec=3)
    test_db_session.add(cfg)
    test_db_session.commit()
    test_db_session.refresh(cfg)
    return cfg.id


def test_save_post_right(svc, config_id, test_db_session):
    """R: 저장 후 DB 조회 → 동일 내용 확인"""
    from app.models.kakao_monitor import KakaoCollectedPost
    post = svc.save_collected_post(
        config_id=config_id,
        keyword_id=None,
        matched_keyword="예약",
        trigger_msg="예약 오픈!",
        content="게시물 전체 내용",
    )
    db_post = test_db_session.get(KakaoCollectedPost, post.id)
    assert db_post is not None
    assert db_post.matched_keyword == "예약"
    assert db_post.collected_content == "게시물 전체 내용"


def test_save_post_created_at_auto(svc, config_id):
    """T: collected_at 자동 설정 확인"""
    before = datetime.now()
    post = svc.save_collected_post(config_id=config_id, keyword_id=None,
                                    matched_keyword="k", trigger_msg="t", content="c")
    after = datetime.now()
    assert post.collected_at is not None
    assert before <= post.collected_at <= after


def test_get_posts_pagination_right(svc, config_id):
    """R: 10건 중 skip=2, limit=3 → 3건 반환"""
    for i in range(10):
        svc.save_collected_post(config_id=config_id, keyword_id=None,
                                 matched_keyword=f"kw{i}", trigger_msg="t", content="c")
    items, total = svc.get_collected_posts(skip=2, limit=3)
    assert len(items) == 3
    assert total >= 10


def test_get_posts_pagination_boundary(svc, config_id):
    """B: limit=0 → 0건"""
    svc.save_collected_post(config_id=config_id, keyword_id=None,
                             matched_keyword="k", trigger_msg="t", content="c")
    items, _ = svc.get_collected_posts(skip=0, limit=0)
    assert len(items) == 0


def test_get_posts_filter_by_config(svc, config_id, test_db_session):
    """R: config_id 필터 정상 동작"""
    from app.models.kakao_monitor import KakaoWatchConfig
    other = KakaoWatchConfig(chat_name="다른방", polling_interval_sec=5)
    test_db_session.add(other)
    test_db_session.commit()

    svc.save_collected_post(config_id=config_id, keyword_id=None,
                             matched_keyword="k1", trigger_msg="t", content="c")
    svc2 = __import__("app.modules.kakao_monitor.services.collect_service",
                       fromlist=["KakaoCollectService"]).KakaoCollectService(test_db_session)
    svc2.save_collected_post(config_id=other.id, keyword_id=None,
                              matched_keyword="k2", trigger_msg="t", content="c")

    items, total = svc.get_collected_posts(config_id=config_id)
    assert all(p.config_id == config_id for p in items)


def test_get_posts_total_count(svc, config_id):
    """Ca: total count 정확성"""
    items0, total0 = svc.get_collected_posts(config_id=config_id)
    svc.save_collected_post(config_id=config_id, keyword_id=None,
                             matched_keyword="k", trigger_msg="t", content="c")
    items1, total1 = svc.get_collected_posts(config_id=config_id)
    assert total1 == total0 + 1


def test_get_posts_order_desc(svc, config_id):
    """O: collected_at 내림차순 정렬"""
    for i in range(3):
        svc.save_collected_post(config_id=config_id, keyword_id=None,
                                 matched_keyword=f"kw{i}", trigger_msg="t", content="c")
    items, _ = svc.get_collected_posts(config_id=config_id)
    times = [p.collected_at for p in items if p.collected_at]
    assert times == sorted(times, reverse=True)


def test_save_post_invalid_config_id(svc):
    """Re: 존재하지 않는 config_id → 에러 발생"""
    from sqlalchemy.exc import IntegrityError
    with pytest.raises(Exception):
        svc.save_collected_post(config_id=99999, keyword_id=None,
                                 matched_keyword="k", trigger_msg="t", content="c")


def test_save_screenshot_right(svc, config_id, tmp_path, monkeypatch):
    """R: 이미지 저장 → 파일 존재 + 경로 반환"""
    try:
        from PIL import Image
        img = Image.new("RGB", (100, 100), color=(0, 0, 0))
    except ImportError:
        pytest.skip("Pillow 미설치")

    monkeypatch.setattr(
        "app.modules.kakao_monitor.services.collect_service._SCREENSHOT_DIR",
        tmp_path
    )
    path = svc.save_screenshot(img, config_id)
    assert Path(path).exists()
    assert str(config_id) in path


def test_save_screenshot_directory_creation(svc, config_id, tmp_path, monkeypatch):
    """E: 디렉토리 미존재 시 자동 생성"""
    new_dir = tmp_path / "new_sub" / "screenshots"
    try:
        from PIL import Image
        img = Image.new("RGB", (10, 10))
    except ImportError:
        pytest.skip("Pillow 미설치")

    monkeypatch.setattr(
        "app.modules.kakao_monitor.services.collect_service._SCREENSHOT_DIR",
        new_dir
    )
    path = svc.save_screenshot(img, config_id)
    assert new_dir.exists()
    assert Path(path).exists()
