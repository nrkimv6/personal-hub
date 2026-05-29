from pathlib import Path

from app.modules.dev_runner.schemas import RunStatusResponse
from app.modules.dev_runner.services.outcome_service import (
    evaluate_outcome_from_events,
    parse_outcome_summary,
)
from app.modules.dev_runner.services.plan_service import PlanService
from app.modules.dev_runner.services.runner_read_model import build_runner_read_model


def test_parse_outcome_section_right_full_fields():
    content = """# plan

## Outcome
- Outcome: Operator can tell whether the product behavior passed.
- Verifier: targeted pytest [satisfied]
- Verifier: source contract [satisfied]
- Rollback signal: none
- Evidence source: logs/run-1.json
"""

    summary = parse_outcome_summary(content, updated_at="2026-05-29T00:00:00Z")

    assert summary.status == "satisfied"
    assert summary.outcome == "Operator can tell whether the product behavior passed."
    assert [v.name for v in summary.verifiers] == ["targeted pytest", "source contract"]
    assert [v.status for v in summary.verifiers] == ["satisfied", "satisfied"]
    assert summary.evidence == ["logs/run-1.json"]
    assert summary.rollback_signal == "none"
    assert summary.updated_at == "2026-05-29T00:00:00Z"


def test_parse_outcome_section_right_minimal_fields():
    summary = parse_outcome_summary("""## Outcome\nOutcome: Summary is visible.\nVerifier: unit test\n""")

    assert summary.status == "pending"
    assert summary.outcome == "Summary is visible."
    assert len(summary.verifiers) == 1


def test_parse_outcome_section_boundary_missing_section():
    summary = parse_outcome_summary("# plan\n\n## TODO\n- [ ] item\n")

    assert summary.status == "absent"
    assert summary.verifiers == []


def test_parse_outcome_section_boundary_multiple_verifiers():
    summary = parse_outcome_summary(
        """## Outcome
Outcome: done
Verifier: no status
Verifier: passed verifier [passed]
Verifier: failed verifier [failed]
"""
    )

    assert [v.status for v in summary.verifiers] == ["pending", "satisfied", "failed"]
    assert summary.status == "failed"


def test_evaluate_outcome_error_failed_verifier_blocks_completed():
    summary = parse_outcome_summary("## Outcome\nOutcome: done\nVerifier: pytest [satisfied]\n")
    evaluated = evaluate_outcome_from_events(
        summary,
        [{"failure": {"classification": "product"}, "raw": "[FAILURE] assertion failed"}],
    )

    assert evaluated.status == "failed"
    assert evaluated.rollback_signal == "[FAILURE] assertion failed"


def test_evaluate_outcome_inverse_rollback_signal_flips_status():
    summary = parse_outcome_summary("## Outcome\nOutcome: done\nVerifier: pytest [satisfied]\n")
    evaluated = evaluate_outcome_from_events(summary, [{"raw": "rollback signal: regression detected"}])

    assert evaluated.status == "blocked"
    assert "rollback" in evaluated.rollback_signal


def test_plan_detail_includes_absent_outcome_without_template_mutation(tmp_path: Path):
    plan = tmp_path / "plan.md"
    before = "# plan\n\n## TODO\n1. [ ] item\n"
    plan.write_text(before, encoding="utf-8")

    detail = PlanService().parse_plan_items(plan)

    assert detail.outcome_summary.status == "absent"
    assert plan.read_text(encoding="utf-8") == before


def test_plan_detail_includes_outcome_summary(tmp_path: Path):
    plan = tmp_path / "plan.md"
    plan.write_text(
        "# plan\n\n## Outcome\nOutcome: done\nVerifier: pytest [satisfied]\n\n## TODO\n1. [x] item\n",
        encoding="utf-8",
    )

    detail = PlanService().parse_plan_items(plan)

    assert detail.outcome_summary.status == "satisfied"
    assert detail.outcome_summary.outcome == "done"


def test_runner_read_model_accepts_optional_outcome_summary():
    model = build_runner_read_model(
        runner_id="r1",
        running=False,
        merge_status="merged",
        exit_reason="completed",
        outcome_summary={"status": "satisfied", "outcome": "done"},
    )

    assert model.outcome_summary == {"status": "satisfied", "outcome": "done"}
    response = RunStatusResponse(running=False, listener_alive=True, redis_connected=True, outcome_summary=model.outcome_summary)
    assert response.model_dump()["outcome_summary"]["status"] == "satisfied"
