"""
verify_completion() 유닛테스트

Right-BICEP + Correct 원칙 기반
"""
import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from app.modules.dev_runner.schemas import VerifyResult, PlanItemResponse, PlanPhaseResponse, PlanDetailResponse, PlanProgressResponse
from app.modules.dev_runner.services.plan_service import plan_service


# ========== 헬퍼 ==========

def _make_detail(items: list[PlanItemResponse], phase_name: str = "Phase 1") -> PlanDetailResponse:
    """테스트용 PlanDetailResponse 생성"""
    done = sum(1 for i in items if i.checked)
    total = len(items)
    return PlanDetailResponse(
        path="/dummy/plan.md",
        filename="plan.md",
        status="구현중",
        phases=[PlanPhaseResponse(
            name=phase_name,
            items=items,
            done_count=done,
            total_count=total,
        )],
        progress=PlanProgressResponse(done=done, total=total, percent=int(done/total*100) if total > 0 else 0),
    )


def _item(text: str, checked: bool = False, file_path: str | None = None, children: list | None = None) -> PlanItemResponse:
    return PlanItemResponse(level=0, text=text, checked=checked, file_path=file_path, children=children or [])


# ========== Right: 정상 케이스 ==========

def test_right_file_path_exists_verified(tmp_path):
    """file_path 있고 파일 존재 → verified 카운트 증가"""
    f = tmp_path / "service.py"
    f.write_text("# dummy")

    detail = _make_detail([_item("서비스 파일", file_path=str(f))])

    with patch.object(plan_service, 'parse_plan_items', return_value=detail):
        result = plan_service.verify_completion(tmp_path / "plan.md")

    assert result.total == 1
    assert result.verified == 1
    assert result.can_done is True
    assert result.unverified_items == []


# ========== Boundary ==========

def test_boundary_total_zero(tmp_path):
    """체크박스 0개 plan → total=0, can_done=False"""
    detail = _make_detail([])

    with patch.object(plan_service, 'parse_plan_items', return_value=detail):
        result = plan_service.verify_completion(tmp_path / "plan.md")

    assert result.total == 0
    assert result.can_done is False


def test_boundary_only_checked_items(tmp_path):
    """file_path 없는 항목만, 전부 checked=True → can_done=True"""
    items = [
        _item("항목1", checked=True),
        _item("항목2", checked=True),
    ]
    detail = _make_detail(items)

    with patch.object(plan_service, 'parse_plan_items', return_value=detail):
        result = plan_service.verify_completion(tmp_path / "plan.md")

    assert result.total == 2
    assert result.verified == 2
    assert result.can_done is True


def test_boundary_all_file_paths_exist(tmp_path):
    """file_path 전부 존재 → can_done=True"""
    files = [tmp_path / "a.py", tmp_path / "b.py"]
    for f in files:
        f.write_text("# code")

    items = [_item(f.name, file_path=str(f)) for f in files]
    detail = _make_detail(items)

    with patch.object(plan_service, 'parse_plan_items', return_value=detail):
        result = plan_service.verify_completion(tmp_path / "plan.md")

    assert result.can_done is True
    assert result.verified == 2


# ========== Inverse ==========

def test_inverse_can_done_false_excluded_from_batch(tmp_path):
    """can_done=False인 plan은 batch-verify-done 대상에 미포함"""
    items = [_item("미완료", checked=False)]
    detail = _make_detail(items)

    with patch.object(plan_service, 'parse_plan_items', return_value=detail):
        result = plan_service.verify_completion(tmp_path / "plan.md")

    assert result.can_done is False


# ========== Cross-check ==========

def test_cross_check_verified_count_matches_exists(tmp_path):
    """verified 수 == 실제 os.path.exists() True 수"""
    f1 = tmp_path / "exists.py"
    f1.write_text("")
    f2 = tmp_path / "missing.py"  # 생성 안 함

    items = [
        _item("존재", file_path=str(f1)),
        _item("미존재", file_path=str(f2)),
    ]
    detail = _make_detail(items)

    with patch.object(plan_service, 'parse_plan_items', return_value=detail):
        result = plan_service.verify_completion(tmp_path / "plan.md")

    actual_exists = sum(1 for i in items if i.file_path and os.path.exists(i.file_path))
    assert result.verified == actual_exists


# ========== Error ==========

def test_error_nonexistent_file_path(tmp_path):
    """존재하지 않는 file_path → unverified에 추가"""
    items = [_item("없는 파일", file_path="/nonexistent/path/file.py")]
    detail = _make_detail(items)

    with patch.object(plan_service, 'parse_plan_items', return_value=detail):
        result = plan_service.verify_completion(tmp_path / "plan.md")

    assert result.verified == 0
    assert "없는 파일" in result.unverified_items


def test_error_empty_plan(tmp_path):
    """빈 plan → total=0"""
    detail = _make_detail([])

    with patch.object(plan_service, 'parse_plan_items', return_value=detail):
        result = plan_service.verify_completion(tmp_path / "plan.md")

    assert result.total == 0
    assert result.percent == 0.0


# ========== TC (테스트 케이스) ==========

def test_tc1_all_file_paths_exist(tmp_path):
    """TC1: 항목 3개, file_path 전부 존재 → verified=3, can_done=True"""
    files = [tmp_path / f"f{i}.py" for i in range(3)]
    for f in files:
        f.write_text("")

    items = [_item(f.name, file_path=str(f)) for f in files]
    detail = _make_detail(items)

    with patch.object(plan_service, 'parse_plan_items', return_value=detail):
        result = plan_service.verify_completion(tmp_path / "plan.md")

    assert result.verified == 3
    assert result.can_done is True


def test_tc2_one_missing(tmp_path):
    """TC2: 항목 3개, 1개 미존재 → verified=2, can_done=False"""
    f1 = tmp_path / "a.py"; f1.write_text("")
    f2 = tmp_path / "b.py"; f2.write_text("")
    f3 = Path("/nonexistent/c.py")

    items = [_item("a", file_path=str(f1)), _item("b", file_path=str(f2)), _item("c", file_path=str(f3))]
    detail = _make_detail(items)

    with patch.object(plan_service, 'parse_plan_items', return_value=detail):
        result = plan_service.verify_completion(tmp_path / "plan.md")

    assert result.verified == 2
    assert result.can_done is False


def test_tc3_no_file_path_all_checked(tmp_path):
    """TC3: file_path 없음, checked 전부 True → verified=3, can_done=True"""
    items = [_item(f"항목{i}", checked=True) for i in range(3)]
    detail = _make_detail(items)

    with patch.object(plan_service, 'parse_plan_items', return_value=detail):
        result = plan_service.verify_completion(tmp_path / "plan.md")

    assert result.verified == 3
    assert result.can_done is True


def test_tc4_no_file_path_mixed_checked(tmp_path):
    """TC4: file_path 없음, checked 혼재 → can_done=False"""
    items = [
        _item("완료", checked=True),
        _item("미완료", checked=False),
        _item("미완료2", checked=False),
    ]
    detail = _make_detail(items)

    with patch.object(plan_service, 'parse_plan_items', return_value=detail):
        result = plan_service.verify_completion(tmp_path / "plan.md")

    assert result.can_done is False
    assert result.verified == 1


def test_tc5_mixed_file_path_and_checked(tmp_path):
    """TC5: 혼합 (file_path+존재 + checked=True) → 둘 다 verified"""
    f = tmp_path / "svc.py"; f.write_text("")

    items = [
        _item("파일 항목", file_path=str(f)),
        _item("체크 항목", checked=True),
    ]
    detail = _make_detail(items)

    with patch.object(plan_service, 'parse_plan_items', return_value=detail):
        result = plan_service.verify_completion(tmp_path / "plan.md")

    assert result.verified == 2
    assert result.can_done is True


def test_tc6_archive_path_can_done_false(tmp_path):
    """TC6: archive 경로 plan → can_done=False"""
    archive_path = tmp_path / "archive" / "plan.md"
    archive_path.parent.mkdir()
    archive_path.write_text("# 아카이브")

    result = plan_service.verify_completion(archive_path)

    assert result.can_done is False


def test_children_items_are_counted(tmp_path):
    """자식 항목도 total/verified 카운트에 포함"""
    f = tmp_path / "child.py"; f.write_text("")

    parent = _item("부모", checked=True)
    child = PlanItemResponse(level=1, text="자식", checked=False, file_path=str(f), children=[])
    parent.children.append(child)

    detail = _make_detail([parent])

    with patch.object(plan_service, 'parse_plan_items', return_value=detail):
        result = plan_service.verify_completion(tmp_path / "plan.md")

    # parent: checked=True → verified, child: file_path exists → verified
    assert result.total == 2
    assert result.verified == 2
