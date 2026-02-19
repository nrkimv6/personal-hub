"""PlanService 단위 테스트 - RIGHT-BICEP 원칙 적용

대상 소스: app/modules/auto_next/services/plan_service.py
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
    cfg.REGISTERED_PATHS_FILE = tmp_path / "registered_paths.json"
    cfg.IGNORED_PLANS_FILE = tmp_path / "ignored_plans.json"
    (tmp_path / "registered_paths.json").write_text("[]", encoding="utf-8")
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


# ========== validate_path() ==========

class TestValidatePath:

    def test_allowed_path(self, svc, tmp_path):
        """허용 경로 → True"""
        test_path = str(tmp_path / "some" / "plan.md")
        assert svc.validate_path(test_path) is True

    def test_denied_path(self, svc):
        """거부 경로 → False"""
        assert svc.validate_path(r"C:\Windows\system32\evil.md") is False

    def test_path_traversal(self, svc, tmp_path):
        """path traversal → resolve 후 허용 경로 밖이면 False"""
        traversal_path = str(tmp_path / ".." / ".." / ".." / "etc" / "passwd")
        resolved = str(Path(traversal_path).resolve())
        if not resolved.startswith(str(tmp_path)):
            assert svc.validate_path(traversal_path) is False


# ========== list_plans() / 경로 관리 ==========

class TestPathManagement:

    def test_add_and_remove_path(self, svc, tmp_path):
        """add_path / remove_path 영속성"""
        plan_file = tmp_path / "ext_plan.md"
        plan_file.write_text("> 상태: 대기\n\n1. [ ] task", encoding="utf-8")

        assert svc.add_path(str(plan_file)) is True
        assert svc.add_path(str(plan_file)) is False  # 중복

        assert svc.remove_path(str(plan_file)) is True
        assert svc.remove_path(str(plan_file)) is False

    def test_add_and_remove_ignore(self, svc, tmp_path):
        """add_to_ignore / remove_from_ignore 토글"""
        plan_file = tmp_path / "plan.md"
        plan_file.touch()

        assert svc.add_to_ignore(str(plan_file)) is True
        assert svc.add_to_ignore(str(plan_file)) is False

        assert svc.remove_from_ignore(str(plan_file)) is True
        assert svc.remove_from_ignore(str(plan_file)) is False

    def test_list_plans_scans_registered_paths(self, svc, auto_next_config_isolation, tmp_path):
        """등록된 경로 통합 스캔"""
        cfg = auto_next_config_isolation

        folder = tmp_path / "my-project" / "docs" / "plan"
        folder.mkdir(parents=True)
        (folder / "2026-01-01_test.md").write_text(
            "> 상태: 대기\n\n1. [ ] task", encoding="utf-8"
        )

        ext_plan = tmp_path / "single_plan.md"
        ext_plan.write_text("> 상태: 대기\n\n1. [ ] ext task", encoding="utf-8")

        svc._registered_paths = [str(folder), str(ext_plan)]

        results = svc.list_plans()

        filenames = [r.filename for r in results]
        assert "2026-01-01_test.md" in filenames
        assert "single_plan.md" in filenames

        # source 자동 결정 확인
        folder_plan = next(r for r in results if r.filename == "2026-01-01_test.md")
        assert folder_plan.source == "my-project"  # docs/plan 패턴에서 추출


# ========== 폴더 단위 plan 경로 ==========

class TestFolderPath:

    def _make_folder_with_plans(self, base: Path, folder_name: str, plan_names: list[str]) -> Path:
        """임시 plan 폴더 생성 헬퍼"""
        folder = base / folder_name
        folder.mkdir(parents=True, exist_ok=True)
        for name in plan_names:
            (folder / name).write_text("> 상태: 대기\n\n1. [ ] task", encoding="utf-8")
        return folder

    def test_add_folder_path(self, svc, tmp_path):
        """폴더 추가 → list_plans()에서 내부 md 파일 전부 path_type='folder'"""
        folder = self._make_folder_with_plans(
            tmp_path, "plans_folder", ["plan_a.md", "plan_b.md"]
        )
        svc._registered_paths = [str(folder)]

        results = svc.list_plans(include_ignored=True)
        folder_plans = [r for r in results if r.path_type == "folder"]

        filenames = {r.filename for r in folder_plans}
        assert "plan_a.md" in filenames
        assert "plan_b.md" in filenames

    def test_folder_skips_todo(self, svc, tmp_path):
        """폴더 내 _todo.md 파일은 list_plans() 결과에서 제외"""
        folder = self._make_folder_with_plans(
            tmp_path, "plans_folder", ["plan_a.md", "plan_a_todo.md"]
        )
        svc._registered_paths = [str(folder)]

        results = svc.list_plans(include_ignored=True)
        filenames = [r.filename for r in results]

        assert "plan_a.md" in filenames
        assert "plan_a_todo.md" not in filenames

    def test_nonexistent_folder_ignored(self, svc, tmp_path):
        """존재하지 않는 폴더 경로 → list_plans()에서 무시 (에러 없음)"""
        nonexistent = str(tmp_path / "does_not_exist")
        svc._registered_paths = [nonexistent]

        results = svc.list_plans(include_ignored=True)
        assert len(results) == 0

    def test_path_add_remove_roundtrip(self, svc, tmp_path):
        """경로 add → remove → list_plans()에서 사라짐"""
        folder = self._make_folder_with_plans(tmp_path, "plans_folder", ["plan_c.md"])

        svc.add_path(str(folder))
        after_add = svc.list_plans(include_ignored=True)
        assert any(r.filename == "plan_c.md" for r in after_add)

        svc.remove_path(str(folder))
        after_remove = svc.list_plans(include_ignored=True)
        assert not any(r.filename == "plan_c.md" for r in after_remove)

    def test_mixed_file_and_folder(self, svc, tmp_path):
        """파일 1개 + 폴더 1개 동시 등록 → 모두 정상 반환"""
        folder = self._make_folder_with_plans(tmp_path, "folder1", ["folder_plan.md"])
        single_file = tmp_path / "file_plan.md"
        single_file.write_text("> 상태: 대기\n\n1. [ ] task", encoding="utf-8")

        svc._registered_paths = [str(folder), str(single_file)]

        results = svc.list_plans(include_ignored=True)
        filenames = {r.filename for r in results}

        assert "folder_plan.md" in filenames
        assert "file_plan.md" in filenames

        folder_plans = [r for r in results if r.filename == "folder_plan.md"]
        file_plans = [r for r in results if r.filename == "file_plan.md"]
        assert folder_plans[0].path_type == "folder"
        assert file_plans[0].path_type == "file"


# ========== _resolve_source() ==========

class TestResolveSource:

    def test_docs_plan_pattern(self, svc, tmp_path):
        """docs/plan 패턴 → 직전 디렉토리명"""
        path = tmp_path / "gentle-words" / "docs" / "plan"
        assert svc._resolve_source(path) == "gentle-words"

    def test_common_pattern(self, svc, tmp_path):
        """common/docs/plan → 'common'"""
        path = tmp_path / "common" / "docs" / "plan"
        assert svc._resolve_source(path) == "common"

    def test_plain_folder(self, svc, tmp_path):
        """docs/plan 패턴 없음 → 폴더명 자체"""
        path = tmp_path / "my-plans"
        assert svc._resolve_source(path) == "my-plans"


# ========== 마이그레이션 ==========

class TestMigration:

    def test_migration_from_external_plans(self, auto_next_config_isolation, tmp_path):
        """external_plans.json만 있고 registered_paths.json이 없을 때 → 마이그레이션"""
        from app.modules.auto_next.services.plan_service import PlanService

        cfg = auto_next_config_isolation
        cfg.REGISTERED_PATHS_FILE = tmp_path / "registered_paths.json"
        cfg.EXTERNAL_PLANS_FILE = tmp_path / "external_plans.json"
        cfg.IGNORED_PLANS_FILE = tmp_path / "ignored_plans.json"
        cfg.WTOOLS_BASE_DIR = tmp_path / "nonexistent_wtools"

        # registered_paths.json 삭제, external_plans.json 생성
        if cfg.REGISTERED_PATHS_FILE.exists():
            cfg.REGISTERED_PATHS_FILE.unlink()
        cfg.EXTERNAL_PLANS_FILE.write_text(json.dumps(["/some/path"]), encoding="utf-8")
        cfg.IGNORED_PLANS_FILE.write_text("[]", encoding="utf-8")

        svc = PlanService()

        assert cfg.REGISTERED_PATHS_FILE.exists()
        data = json.loads(cfg.REGISTERED_PATHS_FILE.read_text(encoding="utf-8"))
        assert "/some/path" in data

    def test_migration_preserves_data(self, auto_next_config_isolation, tmp_path):
        """마이그레이션 후 기존 경로가 모두 보존"""
        from app.modules.auto_next.services.plan_service import PlanService

        cfg = auto_next_config_isolation
        cfg.REGISTERED_PATHS_FILE = tmp_path / "registered_paths.json"
        cfg.EXTERNAL_PLANS_FILE = tmp_path / "external_plans.json"
        cfg.IGNORED_PLANS_FILE = tmp_path / "ignored_plans.json"
        cfg.WTOOLS_BASE_DIR = tmp_path / "nonexistent_wtools"

        paths = ["/path/a", "/path/b", "/path/c"]
        if cfg.REGISTERED_PATHS_FILE.exists():
            cfg.REGISTERED_PATHS_FILE.unlink()
        cfg.EXTERNAL_PLANS_FILE.write_text(json.dumps(paths), encoding="utf-8")
        cfg.IGNORED_PLANS_FILE.write_text("[]", encoding="utf-8")

        svc = PlanService()

        data = json.loads(cfg.REGISTERED_PATHS_FILE.read_text(encoding="utf-8"))
        for p in paths:
            assert p in data

    def test_seed_from_wtools(self, auto_next_config_isolation, tmp_path):
        """WTOOLS_BASE_DIR 존재 시 프로젝트 경로 자동 등록"""
        from app.modules.auto_next.services.plan_service import PlanService

        cfg = auto_next_config_isolation
        cfg.REGISTERED_PATHS_FILE = tmp_path / "registered_paths.json"
        cfg.EXTERNAL_PLANS_FILE = tmp_path / "external_plans.json"
        cfg.IGNORED_PLANS_FILE = tmp_path / "ignored_plans.json"

        wtools = tmp_path / "wtools"
        project_plan = wtools / "project-a" / "docs" / "plan"
        project_plan.mkdir(parents=True)
        (project_plan / "test.md").write_text("test", encoding="utf-8")

        cfg.WTOOLS_BASE_DIR = wtools
        cfg.PLAN_DIR = Path("common/docs/plan")
        cfg.PROJECT_DIRS = ["project-a"]

        if cfg.REGISTERED_PATHS_FILE.exists():
            cfg.REGISTERED_PATHS_FILE.unlink()
        cfg.IGNORED_PLANS_FILE.write_text("[]", encoding="utf-8")

        svc = PlanService()

        data = json.loads(cfg.REGISTERED_PATHS_FILE.read_text(encoding="utf-8"))
        assert any("project-a" in p for p in data)

    def test_no_wtools_no_seed(self, auto_next_config_isolation, tmp_path):
        """WTOOLS_BASE_DIR 미존재 시 빈 상태 시작"""
        from app.modules.auto_next.services.plan_service import PlanService

        cfg = auto_next_config_isolation
        cfg.REGISTERED_PATHS_FILE = tmp_path / "registered_paths.json"
        cfg.EXTERNAL_PLANS_FILE = tmp_path / "external_plans.json"
        cfg.IGNORED_PLANS_FILE = tmp_path / "ignored_plans.json"
        cfg.WTOOLS_BASE_DIR = tmp_path / "nonexistent_wtools"

        if cfg.REGISTERED_PATHS_FILE.exists():
            cfg.REGISTERED_PATHS_FILE.unlink()
        cfg.IGNORED_PLANS_FILE.write_text("[]", encoding="utf-8")

        svc = PlanService()

        assert svc._registered_paths == []

    def test_skip_if_already_migrated(self, auto_next_config_isolation, tmp_path):
        """registered_paths.json이 이미 있으면 마이그레이션 스킵"""
        from app.modules.auto_next.services.plan_service import PlanService

        cfg = auto_next_config_isolation
        cfg.REGISTERED_PATHS_FILE = tmp_path / "registered_paths.json"
        cfg.EXTERNAL_PLANS_FILE = tmp_path / "external_plans.json"
        cfg.IGNORED_PLANS_FILE = tmp_path / "ignored_plans.json"
        cfg.WTOOLS_BASE_DIR = tmp_path / "nonexistent_wtools"

        # 이미 마이그레이션됨
        cfg.REGISTERED_PATHS_FILE.write_text(json.dumps(["/existing/path"]), encoding="utf-8")
        cfg.EXTERNAL_PLANS_FILE.write_text(json.dumps(["/should/not/appear"]), encoding="utf-8")
        cfg.IGNORED_PLANS_FILE.write_text("[]", encoding="utf-8")

        svc = PlanService()

        # external의 내용이 추가되지 않음 (마이그레이션 스킵)
        assert "/existing/path" in svc._registered_paths
        assert "/should/not/appear" not in svc._registered_paths
