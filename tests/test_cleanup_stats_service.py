"""
CleanupStatsService 단위 테스트
"""
import pytest


def test_cleanup_stats_import():
    """R(Right): CleanupStatsService import 성공"""
    from app.modules.system.services.cleanup_stats_service import CleanupStatsService
    assert CleanupStatsService is not None


@pytest.mark.asyncio
async def test_cleanup_stats_no_logs(tmp_path, monkeypatch):
    """B(Boundary): 로그 없음 → runs=[], summary.total_runs=0"""
    from app.modules.system.services.cleanup_stats_service import CleanupStatsService
    from pathlib import Path

    # log_dir을 빈 tmp_path로 패치
    import app.modules.system.services.cleanup_stats_service as mod
    monkeypatch.setattr(mod, "__name__", mod.__name__)  # 모듈 접근용

    svc = CleanupStatsService()

    # CleanupStatsService가 사용하는 log_dir을 tmp_path로 교체
    original_get = mod.Path
    def patched_path(*args, **kwargs):
        p = original_get(*args, **kwargs)
        return p
    # 직접 메서드를 패치하여 빈 디렉토리 사용
    import unittest.mock as mock
    with mock.patch("app.modules.system.services.cleanup_stats_service.Path") as MockPath:
        mock_dir = mock.MagicMock()
        mock_dir.__truediv__ = lambda self, other: tmp_path / other
        MockPath.return_value = mock_dir

        result = await svc.get_nightly_cleanup_stats(days=7)

    assert result["runs"] == []
    assert result["summary"]["total_runs"] == 0
    assert result["summary"]["total_items_archived"] == 0


@pytest.mark.asyncio
async def test_cleanup_stats_with_log(tmp_path):
    """R(Right): 로그 파일 파싱 → 정상 runs 반환"""
    from app.modules.system.services.cleanup_stats_service import CleanupStatsService
    from datetime import date
    import unittest.mock as mock

    today = date.today()
    log_content = f"""Done Cleanup Log
    - activity-hub: 52 items
    - monitor-page: 10 items
Total Items Archived: 62
Processed: 62
Failed: 0
Skipped: 5
Duration: 00:01:23
"""
    log_file = tmp_path / f"done-cleanup-{today.strftime('%Y-%m-%d')}.log"
    log_file.write_text(log_content, encoding="utf-8")

    svc = CleanupStatsService()
    with mock.patch("app.modules.system.services.cleanup_stats_service.Path") as MockPath:
        mock_dir = mock.MagicMock()
        mock_dir.__truediv__ = lambda self, name: tmp_path / name
        MockPath.return_value = mock_dir

        result = await svc.get_nightly_cleanup_stats(days=1)

    assert len(result["runs"]) == 1
    run = result["runs"][0]
    assert run["total_items"] == 62
    assert run["projects"].get("activity-hub") == 52
    assert run["duration"] == "00:01:23"
    assert result["summary"]["total_runs"] == 1
