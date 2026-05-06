"""plan 상태/claim 조합 회귀 테스트 — T3

`상태: 검토완료` + `> 실행점유: claim` 조합이 완료/폐기 상태로 오분류되지 않는지 검증한다.
claim 헤더 추가가 기존 plan 상태 파싱을 깨지 않음을 보장한다.
"""
import pytest
from pathlib import Path

from app.modules.dev_runner.schemas import PlanProgressResponse


@pytest.fixture
def svc(tmp_path, dev_runner_config_isolation):
    from app.modules.dev_runner.services.plan_service import PlanService
    cfg = dev_runner_config_isolation
    cfg.REGISTERED_PATHS_FILE = tmp_path / "registered_paths.json"
    cfg.IGNORED_PLANS_FILE = tmp_path / "ignored_plans.json"
    (tmp_path / "registered_paths.json").write_text("[]", encoding="utf-8")
    (tmp_path / "ignored_plans.json").write_text("[]", encoding="utf-8")
    return PlanService()


def _write_plan(tmp_path: Path, filename: str, content: str) -> Path:
    p = tmp_path / filename
    p.write_text(content, encoding="utf-8")
    return p


# ─────────────────────────────────────────────────────────
# 상태 파싱 회귀: claim 헤더가 있어도 상태 파싱 결과 불변
# ─────────────────────────────────────────────────────────

class TestGetPlanStatusWithClaimHeader:
    """get_plan_status() — 실행점유 헤더 존재 시 기존 상태 파싱 결과 불변 검증."""

    def test_R_status_preserved_with_claim_header(self, svc, tmp_path):
        """R: 실행점유 헤더가 있어도 기존 상태(검토완료)가 그대로 파싱된다"""
        plan = _write_plan(tmp_path, "test-regression.md", """\
# 테스트 계획

> 상태: 검토완료
> 실행점유: claim-abc-123
> 진행률: 0/5 (0%)
""")
        status = svc.get_plan_status(plan)
        assert status == "검토완료", f"예상 '검토완료' 이지만 실제: '{status}'"

    def test_R_status_preserved_when_claim_before_status(self, svc, tmp_path):
        """R: 실행점유 헤더가 상태 헤더보다 앞에 있어도 상태 파싱이 정상이다"""
        plan = _write_plan(tmp_path, "test-regression-order.md", """\
# 테스트 계획

> 실행점유: claim-abc-123
> 상태: 구현중
> 진행률: 2/5 (40%)
""")
        status = svc.get_plan_status(plan)
        assert status == "구현중", f"예상 '구현중' 이지만 실제: '{status}'"

    def test_B_claim_header_empty_does_not_affect_status(self, svc, tmp_path):
        """B: 실행점유가 빈 값이어도 상태 파싱에 영향 없다"""
        plan = _write_plan(tmp_path, "test-empty-claim.md", """\
# 테스트 계획

> 실행점유:
> 상태: 검토완료
""")
        status = svc.get_plan_status(plan)
        assert status == "검토완료"

    def test_B_claim_value_not_misread_as_status(self, svc, tmp_path):
        """B: 실행점유 값이 '완료'처럼 보여도 상태로 오인식하지 않는다"""
        plan = _write_plan(tmp_path, "test-claim-val-mimic.md", """\
# 테스트 계획

> 실행점유: 완료-claim-id-001
> 상태: 구현중
""")
        status = svc.get_plan_status(plan)
        assert status == "구현중", (
            f"실행점유 값 '완료-claim-id-001'을 상태로 오인식함: '{status}'"
        )


# ─────────────────────────────────────────────────────────
# _is_ignored_plan 회귀: 검토완료 + claim 조합은 무시 대상 아님
# ─────────────────────────────────────────────────────────

class TestIsIgnoredPlanWithClaim:
    """_is_ignored_plan() — claim 헤더 존재 시 오분류 방지."""

    def test_R_review_complete_with_claim_not_ignored(self, svc, tmp_path):
        """R: 상태=검토완료 + claim 존재 → _is_ignored_plan이 False를 반환한다"""
        path = tmp_path / "test-claim-review.md"
        progress = PlanProgressResponse(done=0, total=5, percent=0)
        assert svc._is_ignored_plan(path, "검토완료", progress) is False

    def test_R_active_with_claim_not_ignored(self, svc, tmp_path):
        """R: 상태=구현중 + claim 존재 → _is_ignored_plan이 False를 반환한다"""
        path = tmp_path / "test-claim-active.md"
        progress = PlanProgressResponse(done=2, total=5, percent=40)
        assert svc._is_ignored_plan(path, "구현중", progress) is False

    def test_B_done_status_with_claim_is_ignored(self, svc, tmp_path):
        """B: 상태=완료 (done 계열) + claim → claim 존재 무관, 무시 대상이다"""
        path = tmp_path / "test-done-claim.md"
        progress = PlanProgressResponse(done=5, total=5, percent=100)
        assert svc._is_ignored_plan(path, "완료", progress) is True

    def test_Co_claim_header_in_file_with_review_complete_still_shown(self, svc, tmp_path):
        """Co: 파일에 실행점유 헤더가 있는 검토완료 plan → get_plan_status와 _is_ignored_plan 모두 일관성 있다"""
        plan = _write_plan(tmp_path, "test-co-review-claim.md", """\
# 검토완료 계획

> 상태: 검토완료
> 실행점유: claim-xyz-789
> 진행률: 0/3 (0%)

## 체크리스트

- [ ] 항목 1
- [ ] 항목 2
- [ ] 항목 3
""")
        status = svc.get_plan_status(plan)
        progress = PlanProgressResponse(done=0, total=3, percent=0)
        is_ignored = svc._is_ignored_plan(plan, status, progress)

        assert status == "검토완료"
        assert is_ignored is False, "검토완료 + claim 조합이 무시 대상으로 오분류됨"
