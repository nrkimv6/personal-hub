"""PlanService 단위 테스트 - RIGHT-BICEP 원칙 적용

대상 소스: app/modules/auto_next/services/plan_service.py
Phase 1 of auto-next-test-enhancement plan
"""

import json
import pytest
from pathlib import Path
from unittest.mock import patch

from app.modules.auto_next.schemas import PlanProgressResponse


# ========== Fixtures ==========

@pytest.fixture
def tmp_plan_dir(tmp_path):
    """임시 plan 디렉토리"""
    plan_dir = tmp_path / "plan"
    plan_dir.mkdir()
    return plan_dir


@pytest.fixture
def svc(tmp_path, auto_next_config_isolation):
    """격리된 PlanService 인스턴스"""
    from app.modules.auto_next.services.plan_service import PlanService

    cfg = auto_next_config_isolation
    cfg.EXTERNAL_PLANS_FILE = tmp_path / "external_plans.json"
    cfg.IGNORED_PLANS_FILE = tmp_path / "ignored_plans.json"
    (tmp_path / "external_plans.json").write_text("[]", encoding="utf-8")
    (tmp_path / "ignored_plans.json").write_text("[]", encoding="utf-8")

    return PlanService()


def _write_plan(plan_dir: Path, filename: str, content: str) -> Path:
    p = plan_dir / filename
    p.write_text(content, encoding="utf-8")
    return p


# ========== _is_ignored_plan() ==========

class TestIsIgnoredPlan:

    def test_status_complete_is_ignored(self, svc, tmp_path):
        """상태가 '완료'인 plan → True"""
        path = tmp_path / "test.md"
        progress = PlanProgressResponse(done=0, total=1, percent=0)
        assert svc._is_ignored_plan(path, "완료", progress) is True

    def test_status_impl_complete_is_ignored(self, svc, tmp_path):
        """상태가 '구현완료'인 plan → True"""
        path = tmp_path / "test.md"
        progress = PlanProgressResponse(done=0, total=1, percent=0)
        assert svc._is_ignored_plan(path, "구현완료", progress) is True

    def test_all_checkboxes_done_is_ignored(self, svc, tmp_path):
        """100% 체크박스 완료 (done == total > 0) → True"""
        path = tmp_path / "test.md"
        progress = PlanProgressResponse(done=5, total=5, percent=100)
        assert svc._is_ignored_plan(path, "구현중", progress) is True

    def test_zero_checkboxes_not_ignored(self, svc, tmp_path):
        """체크박스 0개 (total=0)인 plan → False"""
        path = tmp_path / "test.md"
        progress = PlanProgressResponse(done=0, total=0, percent=0)
        assert svc._is_ignored_plan(path, "대기", progress) is False

    def test_manual_ignore_list(self, svc, tmp_path):
        """ignored_plans.json에 등록된 경로 → True"""
        path = tmp_path / "test.md"
        path.touch()
        svc._ignored_plans.append(str(path.resolve()))
        progress = PlanProgressResponse(done=0, total=5, percent=0)
        assert svc._is_ignored_plan(path, "대기", progress) is True

    def test_partial_progress_not_ignored(self, svc, tmp_path):
        """부분 완료 (3/5) → False"""
        path = tmp_path / "test.md"
        progress = PlanProgressResponse(done=3, total=5, percent=60)
        assert svc._is_ignored_plan(path, "구현중", progress) is False


# ========== parse_plan_items() ==========

class TestParsePlanItems:

    def test_phase_with_numbered_and_dash_items(self, svc, tmp_plan_dir):
        """Phase/항목 중첩 구조 파싱"""
        content = """\
# Test Plan

> 상태: 구현중

## Phase 1: 기본 기능

1. [x] 첫 번째 기능 `app/main.py`
   - [x] 하위 작업 A
   - [ ] 하위 작업 B
2. [ ] 두 번째 기능

## Phase 2: 고급 기능

1. [ ] 세 번째 기능
"""
        path = _write_plan(tmp_plan_dir, "test.md", content)
        result = svc.parse_plan_items(path)

        assert len(result.phases) == 2
        assert "Phase 1" in result.phases[0].name
        assert len(result.phases[0].items) == 2
        assert result.phases[0].items[0].checked is True
        assert result.phases[0].items[0].file_path == "app/main.py"
        assert len(result.phases[0].items[0].children) == 2
        assert result.phases[0].items[0].children[0].checked is True
        assert result.phases[0].items[0].children[1].checked is False

    def test_checkbox_formats(self, svc, tmp_plan_dir):
        """다양한 체크박스 형식: [x], [ ], [→]"""
        content = """\
## Phase 1: Test

1. [x] checked item
2. [ ] unchecked item
3. [→] arrow item (in progress)
"""
        path = _write_plan(tmp_plan_dir, "test.md", content)
        result = svc.parse_plan_items(path)

        items = result.phases[0].items
        assert items[0].checked is True
        assert items[1].checked is False
        assert items[2].checked is False  # → is not 'x'

    def test_empty_file(self, svc, tmp_plan_dir):
        """빈 파일 → 빈 phases"""
        path = _write_plan(tmp_plan_dir, "empty.md", "")
        result = svc.parse_plan_items(path)
        assert result.phases == []

    def test_no_checkboxes(self, svc, tmp_plan_dir):
        """체크박스 없는 파일 → 빈 phases"""
        content = "# Just a title\n\nSome text without checkboxes.\n"
        path = _write_plan(tmp_plan_dir, "no_cb.md", content)
        result = svc.parse_plan_items(path)
        assert result.phases == []

    def test_nonexistent_path_raises(self, svc, tmp_path):
        """존재하지 않는 경로 → 예외"""
        path = tmp_path / "nonexistent.md"
        with pytest.raises(Exception):
            svc.parse_plan_items(path)

    def test_todo_file_preferred(self, svc, tmp_plan_dir):
        """_todo.md 파일이 있으면 우선 사용"""
        main_content = """\
# Plan

> 상태: 구현중

## Phase 1: Main
1. [ ] main item
"""
        todo_content = """\
## Phase 1: Todo

1. [x] todo item A
2. [ ] todo item B
"""
        _write_plan(tmp_plan_dir, "test.md", main_content)
        _write_plan(tmp_plan_dir, "test_todo.md", todo_content)

        path = tmp_plan_dir / "test.md"
        result = svc.parse_plan_items(path)

        assert result.phases[0].items[0].text == "todo item A"
        assert result.status == "구현중"

    def test_done_count_includes_children(self, svc, tmp_plan_dir):
        """done_count에 children 포함"""
        content = """\
## Phase 1: Test

1. [x] parent
   - [x] child 1
   - [ ] child 2
"""
        path = _write_plan(tmp_plan_dir, "test.md", content)
        result = svc.parse_plan_items(path)

        phase = result.phases[0]
        assert phase.done_count == 2  # parent(1) + child1(1)
        assert phase.total_count == 3  # parent(1) + children(2)


# ========== get_plan_progress() / get_plan_status() ==========

class TestGetPlanProgress:

    def test_progress_count(self, svc, tmp_plan_dir):
        """done/total 카운트 정확성"""
        content = """\
1. [x] done 1
2. [ ] pending
- [x] done 2
- [ ] pending 2
"""
        path = _write_plan(tmp_plan_dir, "test.md", content)
        result = svc.get_plan_progress(path)

        assert result.total == 4
        assert result.done == 2
        assert result.percent == 50

    def test_status_extraction(self, svc, tmp_plan_dir):
        """'> 상태: 완료' 라인 추출"""
        content = "> 상태: 완료\n\nSome content"
        path = _write_plan(tmp_plan_dir, "test.md", content)
        assert svc.get_plan_status(path) == "완료"

    def test_status_missing(self, svc, tmp_plan_dir):
        """상태 라인 없는 파일 → 'unknown'"""
        content = "# No status line\n\nJust content."
        path = _write_plan(tmp_plan_dir, "test.md", content)
        assert svc.get_plan_status(path) == "unknown"

    def test_progress_nonexistent_file(self, svc, tmp_path):
        """존재하지 않는 파일 → (0, 0, 0)"""
        result = svc.get_plan_progress(tmp_path / "no_file.md")
        assert result.done == 0 and result.total == 0 and result.percent == 0

    def test_status_nonexistent_file(self, svc, tmp_path):
        """존재하지 않는 파일 → 'unknown'"""
        assert svc.get_plan_status(tmp_path / "no.md") == "unknown"


# ========== validate_external_path() ==========

class TestValidateExternalPath:

    def test_allowed_path(self, svc, tmp_path):
        """허용 경로 → True"""
        test_path = str(tmp_path / "some" / "plan.md")
        assert svc.validate_external_path(test_path) is True

    def test_denied_path(self, svc):
        """거부 경로 → False"""
        assert svc.validate_external_path(r"C:\Windows\system32\evil.md") is False

    def test_path_traversal(self, svc, tmp_path):
        """path traversal → resolve 후 허용 경로 밖이면 False"""
        traversal_path = str(tmp_path / ".." / ".." / ".." / "etc" / "passwd")
        resolved = str(Path(traversal_path).resolve())
        if not resolved.startswith(str(tmp_path)):
            assert svc.validate_external_path(traversal_path) is False


# ========== list_plans() / 외부 plan 관리 ==========

class TestExternalPlanManagement:

    def test_add_and_remove_external_plan(self, svc, tmp_path):
        """add_external_plan / remove_external_plan 영속성"""
        plan_file = tmp_path / "ext_plan.md"
        plan_file.write_text("> 상태: 대기\n\n1. [ ] task", encoding="utf-8")

        assert svc.add_external_plan(str(plan_file)) is True
        assert svc.add_external_plan(str(plan_file)) is False  # 중복

        assert svc.remove_external_plan(str(plan_file)) is True
        assert svc.remove_external_plan(str(plan_file)) is False

    def test_add_and_remove_ignore(self, svc, tmp_path):
        """add_to_ignore / remove_from_ignore 토글"""
        plan_file = tmp_path / "plan.md"
        plan_file.touch()

        assert svc.add_to_ignore(str(plan_file)) is True
        assert svc.add_to_ignore(str(plan_file)) is False

        assert svc.remove_from_ignore(str(plan_file)) is True
        assert svc.remove_from_ignore(str(plan_file)) is False

    def test_list_plans_scans_common_and_external(self, svc, auto_next_config_isolation, tmp_path):
        """common + external 소스 통합 스캔"""
        cfg = auto_next_config_isolation
        wtools_dir = tmp_path / "wtools"
        common_plan = wtools_dir / "common" / "docs" / "plan"
        common_plan.mkdir(parents=True)
        (common_plan / "2026-01-01_test.md").write_text(
            "> 상태: 대기\n\n1. [ ] task", encoding="utf-8"
        )

        ext_plan = tmp_path / "external_plan.md"
        ext_plan.write_text("> 상태: 대기\n\n1. [ ] ext task", encoding="utf-8")

        cfg.WTOOLS_BASE_DIR = wtools_dir
        svc._external_plans = [str(ext_plan)]

        results = svc.list_plans()

        filenames = [r.filename for r in results]
        assert "2026-01-01_test.md" in filenames
        assert "external_plan.md" in filenames


# ========== 폴더 단위 외부 plan 추가 ==========

class TestExternalFolderPlan:

    def _make_folder_with_plans(self, base: Path, folder_name: str, plan_names: list[str]) -> Path:
        """임시 plan 폴더 생성 헬퍼"""
        folder = base / folder_name
        folder.mkdir(parents=True, exist_ok=True)
        for name in plan_names:
            (folder / name).write_text("> 상태: 대기\n\n1. [ ] task", encoding="utf-8")
        return folder

    def test_add_external_folder(self, svc, tmp_path):
        """폴더 추가 → list_plans()에서 내부 md 파일 전부 source='external', external_type='folder'"""
        folder = self._make_folder_with_plans(
            tmp_path, "plans_folder", ["plan_a.md", "plan_b.md"]
        )
        svc._external_plans = [str(folder)]

        results = svc.list_plans(include_ignored=True)
        external = [r for r in results if r.source == "external"]

        filenames = {r.filename for r in external}
        assert "plan_a.md" in filenames
        assert "plan_b.md" in filenames
        for r in external:
            assert r.external_type == "folder"

    def test_folder_skips_todo(self, svc, tmp_path):
        """폴더 내 _todo.md 파일은 list_plans() 결과에서 제외"""
        folder = self._make_folder_with_plans(
            tmp_path, "plans_folder", ["plan_a.md", "plan_a_todo.md"]
        )
        svc._external_plans = [str(folder)]

        results = svc.list_plans(include_ignored=True)
        filenames = [r.filename for r in results]

        assert "plan_a.md" in filenames
        assert "plan_a_todo.md" not in filenames

    def test_nonexistent_folder_ignored(self, svc, tmp_path):
        """존재하지 않는 폴더 경로 → list_plans()에서 무시 (에러 없음)"""
        nonexistent = str(tmp_path / "does_not_exist")
        svc._external_plans = [nonexistent]

        # 에러 없이 빈 결과 반환
        results = svc.list_plans(include_ignored=True)
        assert all(r.source != "external" for r in results)

    def test_folder_add_remove_roundtrip(self, svc, tmp_path):
        """폴더 경로 add → remove → list_plans()에서 사라짐"""
        folder = self._make_folder_with_plans(tmp_path, "plans_folder", ["plan_c.md"])

        svc.add_external_plan(str(folder))
        after_add = svc.list_plans(include_ignored=True)
        assert any(r.filename == "plan_c.md" for r in after_add)

        svc.remove_external_plan(str(folder))
        after_remove = svc.list_plans(include_ignored=True)
        assert not any(r.filename == "plan_c.md" for r in after_remove)

    def test_mixed_file_and_folder(self, svc, tmp_path):
        """파일 1개 + 폴더 1개 동시 등록 → 모두 정상 반환"""
        folder = self._make_folder_with_plans(tmp_path, "folder1", ["folder_plan.md"])
        single_file = tmp_path / "file_plan.md"
        single_file.write_text("> 상태: 대기\n\n1. [ ] task", encoding="utf-8")

        svc._external_plans = [str(folder), str(single_file)]

        results = svc.list_plans(include_ignored=True)
        filenames = {r.filename for r in results if r.source == "external"}

        assert "folder_plan.md" in filenames
        assert "file_plan.md" in filenames

        folder_plans = [r for r in results if r.filename == "folder_plan.md"]
        file_plans = [r for r in results if r.filename == "file_plan.md"]
        assert folder_plans[0].external_type == "folder"
        assert file_plans[0].external_type == "file"
