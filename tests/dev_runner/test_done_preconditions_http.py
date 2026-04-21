"""
Phase T5: HTTP 통합 테스트 — done 사전 검증 (fix plan Phase R)

main 머지 후 실행. TestClient 기반 (실서버 불필요).
- POST /api/v1/dev-runner/plans/{fix_plan}/done 호출 시 Phase R 없으면 success=False
- Phase R 있는 fix plan은 정상 처리
"""
import textwrap
import base64
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import quote

import pytest

from app.modules.dev_runner.routes.plans import router, run_plan_done
from app.modules.dev_runner.services.plan_service import PlanService


@pytest.fixture
def svc(dev_runner_config_isolation):
    return PlanService()


@pytest.mark.http
class TestDonePreconditionsHttp:
    def test_plan_done_api_fix_no_phase_r_returns_failure(self, svc, tmp_path, dev_runner_config_isolation):
        """POST /plans/{fix_plan}/done — Phase R 없으면 success=False 응답"""
        plan_dir = tmp_path / "docs" / "plan"
        plan_dir.mkdir(parents=True, exist_ok=True)
        plan_path = plan_dir / "2026-03-31_fix-test-http.md"
        plan_path.write_text(textwrap.dedent("""\
            # fix: HTTP 테스트

            > 상태: 구현완료
            > 진행률: 2/2 (100%)

            - [x] A
            - [x] B

            *상태: 구현완료 | 진행률: 2/2 (100%)*
        """), encoding="utf-8")

        # _validate_done_preconditions을 직접 테스트 (API 라우터는 run_done 위임)
        result_coro = svc.run_done(str(plan_path))

        import asyncio
        result = asyncio.run(result_coro)

        assert result["success"] is False
        assert "Phase R" in result["message"]

        # plan 파일이 원래 위치에 그대로 있어야 함
        assert plan_path.exists()

    def test_plan_done_api_fix_with_phase_r_succeeds(self, svc, tmp_path, dev_runner_config_isolation):
        """Phase R 있는 fix plan은 정상 처리"""
        plan_dir = tmp_path / "docs" / "plan"
        plan_dir.mkdir(parents=True, exist_ok=True)
        plan_path = plan_dir / "2026-03-31_fix-test-http-ok.md"
        plan_path.write_text(textwrap.dedent("""\
            # fix: HTTP 테스트 OK

            > 상태: 구현완료
            > 진행률: 3/3 (100%)

            - [x] A
            - [x] B

            ### Phase R: 재발 경로 분석

            | 경로 | 방어여부 |
            | path1 | 방어됨 |

            ### T3
            - [x] TC

            *상태: 구현완료 | 진행률: 3/3 (100%)*
        """), encoding="utf-8")

        # TODO.md, DONE.md 생성
        todo_md = tmp_path / "TODO.md"
        todo_md.write_text("# TODO\n\n## In Progress\n\n## Pending\n", encoding="utf-8")
        done_md = tmp_path / "docs" / "DONE.md"
        done_md.write_text("# DONE\n", encoding="utf-8")

        with patch.object(svc, "_git_commit", new=AsyncMock(return_value="commit ok")), \
             patch("app.modules.dev_runner.services.plan_service._publish_log"), \
             patch("app.modules.dev_runner.services.plan_service._get_redis", return_value=MagicMock()):
            import asyncio
            result = asyncio.run(svc.run_done(str(plan_path)))

        assert result["success"] is True

    def test_plan_done_api_prefers_runner_id_header(self, tmp_path, dev_runner_config_isolation):
        """X-Plan-Runner-Id 헤더가 query runner_id보다 우선한다."""
        plan_dir = tmp_path / "docs" / "plan"
        plan_dir.mkdir(parents=True, exist_ok=True)
        plan_path = plan_dir / "2026-03-31_fix-test-http-header.md"
        plan_path.write_text(textwrap.dedent("""\
            # fix: HTTP 헤더 테스트

            > 상태: 구현완료
            > 진행률: 1/1 (100%)

            - [x] A

            ### Phase R: 재발 경로 분석

            | 경로 | 방어여부 |
            | path1 | 방어됨 |

            *상태: 구현완료 | 진행률: 1/1 (100%)*
        """), encoding="utf-8")

        with patch("app.modules.dev_runner.routes.plans.plan_service.validate_path", return_value=True), \
             patch("app.modules.dev_runner.routes.plans.plan_service.run_done", new=AsyncMock(return_value={
                 "success": True,
                 "message": "ok",
                 "output": None,
                 "remaining_tasks": 0,
                 "total_tasks": 1,
                 "plan_status": "구현완료",
             })) as mock_run_done, \
             patch("app.modules.dev_runner.routes.plans.plan_service.list_plans", return_value=[]):
            import asyncio
            result = asyncio.run(
                run_plan_done(
                    base64.urlsafe_b64encode(str(plan_path).encode("utf-8")).decode("ascii").rstrip("="),
                    runner_id="query-runner",
                    x_plan_runner_id="header-runner",
                )
            )

        assert result["success"] is True
        mock_run_done.assert_awaited_once()
        called_args = mock_run_done.await_args.kwargs
        assert called_args["runner_id"] == "header-runner"

    def test_plan_done_api_without_runner_header_stays_manual(self, tmp_path, dev_runner_config_isolation):
        """header/query runner_id가 모두 없으면 manual /done 경로(None)로 호출한다."""
        plan_dir = tmp_path / "docs" / "plan"
        plan_dir.mkdir(parents=True, exist_ok=True)
        plan_path = plan_dir / "2026-03-31_fix-test-http-manual.md"
        plan_path.write_text(textwrap.dedent("""\
            # fix: HTTP manual 테스트

            > 상태: 구현완료
            > 진행률: 1/1 (100%)

            - [x] A

            ### Phase R: 재발 경로 분석

            | 경로 | 방어여부 |
            | path1 | 방어됨 |
        """), encoding="utf-8")

        with patch("app.modules.dev_runner.routes.plans.plan_service.validate_path", return_value=True), \
             patch("app.modules.dev_runner.routes.plans.plan_service.run_done", new=AsyncMock(return_value={
                 "success": True,
                 "message": "ok",
                 "output": None,
                 "remaining_tasks": 0,
                 "total_tasks": 1,
                 "plan_status": "구현완료",
             })) as mock_run_done, \
             patch("app.modules.dev_runner.routes.plans.plan_service.list_plans", return_value=[]):
            import asyncio
            result = asyncio.run(
                run_plan_done(
                    base64.urlsafe_b64encode(str(plan_path).encode("utf-8")).decode("ascii").rstrip("="),
                )
            )

        assert result["success"] is True
        mock_run_done.assert_awaited_once()
        called_args = mock_run_done.await_args.kwargs
        assert called_args["runner_id"] is None

    def test_plan_done_api_resolver_error_returns_failure_E(self, svc, tmp_path, dev_runner_config_isolation):
        """docs/plan 외 경로 plan은 resolver hard-fail 응답(success=false)을 반환한다."""
        plan_dir = tmp_path / "docs" / "tmp"
        plan_dir.mkdir(parents=True, exist_ok=True)
        plan_path = plan_dir / "2026-04-03_resolver-http-fail.md"
        original = textwrap.dedent("""\
            # feat: resolver failure

            > 상태: 구현완료
            > 진행률: 1/1 (100%)

            - [x] done
        """)
        plan_path.write_text(original, encoding="utf-8")

        import asyncio
        result = asyncio.run(svc.run_done(str(plan_path)))

        assert result["success"] is False
        assert "archive target resolve failed" in result["message"]
        assert plan_path.exists()
        assert plan_path.read_text(encoding="utf-8") == original
