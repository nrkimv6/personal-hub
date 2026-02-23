"""PlanService 단위 테스트 - RIGHT-BICEP 원칙 적용

대상 소스: app/modules/dev_runner/services/plan_service.py
"""

import asyncio
import json
import pytest
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

from app.modules.dev_runner.schemas import PlanProgressResponse


# ========== Fixtures ==========

@pytest.fixture
def tmp_plan_dir(tmp_path):
    """임시 plan 디렉토리"""
    plan_dir = tmp_path / "plan"
    plan_dir.mkdir()
    return plan_dir


@pytest.fixture
def svc(tmp_path, dev_runner_config_isolation):
    """격리된 PlanService 인스턴스"""
    from app.modules.dev_runner.services.plan_service import PlanService

    cfg = dev_runner_config_isolation
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

    def test_status_impl_complete_is_not_ignored(self, svc, tmp_path):
        """상태가 '구현완료'인 plan → False (grayout 표시, 무시 아님)"""
        path = tmp_path / "test.md"
        progress = PlanProgressResponse(done=0, total=1, percent=0)
        assert svc._is_ignored_plan(path, "구현완료", progress) is False

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

    def test_review_complete_not_ignored(self, svc, tmp_path):
        """상태가 '검토완료'인 plan → False (검토완료는 구현 완료가 아님)"""
        path = tmp_path / "test.md"
        progress = PlanProgressResponse(done=0, total=5, percent=0)
        assert svc._is_ignored_plan(path, "검토완료", progress) is False


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

    def test_list_plans_scans_registered_paths(self, svc, dev_runner_config_isolation, tmp_path):
        """등록된 경로 통합 스캔"""
        cfg = dev_runner_config_isolation

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

    def test_folder_todo_takes_priority_over_main(self, svc, tmp_path):
        """_todo.md가 있으면 메인 파일 스킵, _todo.md가 대표로 표시"""
        folder = self._make_folder_with_plans(
            tmp_path, "plans_folder", ["plan_a.md", "plan_a_todo.md"]
        )
        svc._registered_paths = [str(folder)]

        results = svc.list_plans(include_ignored=True)
        filenames = [r.filename for r in results]

        assert "plan_a_todo.md" in filenames
        assert "plan_a.md" not in filenames

    def test_folder_shows_orphan_todo(self, svc, tmp_path):
        """메인 파일 없이 _todo.md만 있으면 독립 항목으로 표시"""
        folder = self._make_folder_with_plans(
            tmp_path, "plans_folder", ["plan_b_todo.md"]
        )
        svc._registered_paths = [str(folder)]

        results = svc.list_plans(include_ignored=True)
        filenames = [r.filename for r in results]

        assert "plan_b_todo.md" in filenames

    def test_folder_shows_main_when_no_todo(self, svc, tmp_path):
        """_todo.md가 없으면 메인 파일 그대로 표시"""
        folder = self._make_folder_with_plans(
            tmp_path, "plans_folder", ["plan_c.md"]
        )
        svc._registered_paths = [str(folder)]

        results = svc.list_plans(include_ignored=True)
        filenames = [r.filename for r in results]

        assert "plan_c.md" in filenames

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

    def test_migration_from_external_plans(self, dev_runner_config_isolation, tmp_path):
        """external_plans.json만 있고 registered_paths.json이 없을 때 → 마이그레이션"""
        from app.modules.dev_runner.services.plan_service import PlanService

        cfg = dev_runner_config_isolation
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

    def test_migration_preserves_data(self, dev_runner_config_isolation, tmp_path):
        """마이그레이션 후 기존 경로가 모두 보존"""
        from app.modules.dev_runner.services.plan_service import PlanService

        cfg = dev_runner_config_isolation
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

    def test_seed_from_wtools(self, dev_runner_config_isolation, tmp_path):
        """WTOOLS_BASE_DIR 존재 시 프로젝트 경로 자동 등록"""
        from app.modules.dev_runner.services.plan_service import PlanService

        cfg = dev_runner_config_isolation
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

    def test_no_wtools_no_seed(self, dev_runner_config_isolation, tmp_path):
        """WTOOLS_BASE_DIR 미존재 시 빈 상태 시작"""
        from app.modules.dev_runner.services.plan_service import PlanService

        cfg = dev_runner_config_isolation
        cfg.REGISTERED_PATHS_FILE = tmp_path / "registered_paths.json"
        cfg.EXTERNAL_PLANS_FILE = tmp_path / "external_plans.json"
        cfg.IGNORED_PLANS_FILE = tmp_path / "ignored_plans.json"
        cfg.WTOOLS_BASE_DIR = tmp_path / "nonexistent_wtools"

        if cfg.REGISTERED_PATHS_FILE.exists():
            cfg.REGISTERED_PATHS_FILE.unlink()
        cfg.IGNORED_PLANS_FILE.write_text("[]", encoding="utf-8")

        svc = PlanService()

        assert svc._registered_paths == []

    def test_skip_if_already_migrated(self, dev_runner_config_isolation, tmp_path):
        """registered_paths.json이 이미 있으면 마이그레이션 스킵"""
        from app.modules.dev_runner.services.plan_service import PlanService

        cfg = dev_runner_config_isolation
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


# ========== run_done() ==========

class TestRunDone:
    """run_done() 테스트 - RIGHT-BICEP + CORRECT

    Right: 정상 실행 시 success=True
    Boundary: 존재하지 않는 plan, 존재하지 않는 스크립트
    Inverse: 실패 시 success=False + 에러 메시지
    Cross-check: sync_plans() 호출 여부
    Error: 타임아웃, 예외 발생
    Performance: N/A (subprocess)

    CORRECT:
    Conformance: 반환 dict 구조 검증
    Ordering: N/A
    Range: exit code 0 vs non-zero
    Reference: sync_plans 호출 확인
    Existence: plan 파일 미존재
    Cardinality: N/A
    Time: 타임아웃 처리
    """

    @pytest.mark.asyncio
    async def test_success_returns_true(self, svc, tmp_plan_dir):
        """Right: auto-done.ps1 성공 (exit=0) → success=True, sync 호출"""
        plan = tmp_plan_dir / "done_test.md"
        plan.write_text("> 상태: 구현완료\n\n1. [x] task", encoding="utf-8")

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"Done OK\n", None))
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec, \
             patch.object(svc, "sync_plans") as mock_sync:
            svc.AUTO_DONE_SCRIPT = tmp_plan_dir / "auto-done.ps1"
            (svc.AUTO_DONE_SCRIPT).write_text("# fake", encoding="utf-8")

            result = await svc.run_done(str(plan))

        assert result["success"] is True
        assert "성공" in result["message"]
        assert result["output"] == "Done OK\n"
        assert result["remaining_tasks"] == 0
        assert result["total_tasks"] == 1
        assert result["plan_status"] == "구현완료"
        mock_sync.assert_called_once()

    @pytest.mark.asyncio
    async def test_failure_returns_false(self, svc, tmp_plan_dir):
        """Inverse: auto-done.ps1 실패 (exit=1) → success=False, progress 포함"""
        plan = tmp_plan_dir / "fail_test.md"
        plan.write_text("> 상태: 구현완료\n\n1. [x] task\n2. [ ] pending", encoding="utf-8")

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"Error occurred\n", None))
        mock_proc.returncode = 1

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            svc.AUTO_DONE_SCRIPT = tmp_plan_dir / "auto-done.ps1"
            (svc.AUTO_DONE_SCRIPT).write_text("# fake", encoding="utf-8")

            result = await svc.run_done(str(plan))

        assert result["success"] is False
        assert "실패" in result["message"]
        assert "Error occurred" in result["output"]
        assert result["remaining_tasks"] == 1
        assert result["total_tasks"] == 2
        assert result["plan_status"] == "구현완료"

    @pytest.mark.asyncio
    async def test_nonexistent_plan_file(self, svc, tmp_path):
        """Existence: plan 파일 미존재 → success=False, progress 기본값"""
        svc.AUTO_DONE_SCRIPT = tmp_path / "auto-done.ps1"
        (svc.AUTO_DONE_SCRIPT).write_text("# fake", encoding="utf-8")

        result = await svc.run_done(str(tmp_path / "nonexistent.md"))

        assert result["success"] is False
        assert "not found" in result["message"]
        assert result["remaining_tasks"] == 0
        assert result["total_tasks"] == 0
        assert result["plan_status"] == ""

    @pytest.mark.asyncio
    async def test_nonexistent_script(self, svc, tmp_plan_dir):
        """Existence: auto-done.ps1 미존재 → success=False"""
        plan = tmp_plan_dir / "test.md"
        plan.write_text("content", encoding="utf-8")

        svc.AUTO_DONE_SCRIPT = tmp_plan_dir / "no_script.ps1"

        result = await svc.run_done(str(plan))

        assert result["success"] is False
        assert "not found" in result["message"]

    @pytest.mark.asyncio
    async def test_timeout_handling(self, svc, tmp_plan_dir):
        """Time: 타임아웃 시 success=False, progress 기본값"""
        plan = tmp_plan_dir / "timeout_test.md"
        plan.write_text("content", encoding="utf-8")

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError())

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            svc.AUTO_DONE_SCRIPT = tmp_plan_dir / "auto-done.ps1"
            (svc.AUTO_DONE_SCRIPT).write_text("# fake", encoding="utf-8")

            result = await svc.run_done(str(plan))

        assert result["success"] is False
        assert "타임아웃" in result["message"]
        assert result["remaining_tasks"] == 0
        assert result["total_tasks"] == 0
        assert result["plan_status"] == ""

    @pytest.mark.asyncio
    async def test_exception_handling(self, svc, tmp_plan_dir):
        """Error: 예외 발생 시 success=False + 에러 메시지, progress 기본값"""
        plan = tmp_plan_dir / "exc_test.md"
        plan.write_text("content", encoding="utf-8")

        with patch("asyncio.create_subprocess_exec", side_effect=OSError("spawn failed")):
            svc.AUTO_DONE_SCRIPT = tmp_plan_dir / "auto-done.ps1"
            (svc.AUTO_DONE_SCRIPT).write_text("# fake", encoding="utf-8")

            result = await svc.run_done(str(plan))

        assert result["success"] is False
        assert "spawn failed" in result["message"]
        assert result["remaining_tasks"] == 0
        assert result["total_tasks"] == 0
        assert result["plan_status"] == ""

    @pytest.mark.asyncio
    async def test_response_conformance(self, svc, tmp_plan_dir):
        """Conformance: 반환 dict에 success, message, output, remaining_tasks, total_tasks, plan_status 키가 항상 존재"""
        plan = tmp_plan_dir / "conform_test.md"
        plan.write_text("> 상태: 구현중\n\n1. [x] a\n2. [ ] b", encoding="utf-8")

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"output", None))
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc), \
             patch.object(svc, "sync_plans"):
            svc.AUTO_DONE_SCRIPT = tmp_plan_dir / "auto-done.ps1"
            (svc.AUTO_DONE_SCRIPT).write_text("# fake", encoding="utf-8")

            result = await svc.run_done(str(plan))

        assert "success" in result
        assert "message" in result
        assert "output" in result
        assert "remaining_tasks" in result
        assert "total_tasks" in result
        assert "plan_status" in result

    @pytest.mark.asyncio
    async def test_no_sync_on_failure(self, svc, tmp_plan_dir):
        """Cross-check: 실패 시 sync_plans 호출 안 됨"""
        plan = tmp_plan_dir / "nosync_test.md"
        plan.write_text("content", encoding="utf-8")

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"fail", None))
        mock_proc.returncode = 1

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc), \
             patch.object(svc, "sync_plans") as mock_sync:
            svc.AUTO_DONE_SCRIPT = tmp_plan_dir / "auto-done.ps1"
            (svc.AUTO_DONE_SCRIPT).write_text("# fake", encoding="utf-8")

            await svc.run_done(str(plan))

        mock_sync.assert_not_called()

    # ---- progress 필드 추가 TC (RIGHT-BICEP + CORRECT) ----

    @pytest.mark.asyncio
    async def test_progress_partial_completion(self, svc, tmp_plan_dir):
        """Boundary: 부분 완료 plan (3/5) → remaining_tasks=2, total_tasks=5"""
        plan = tmp_plan_dir / "partial.md"
        plan.write_text(
            "> 상태: 구현중\n\n"
            "1. [x] done1\n2. [x] done2\n3. [x] done3\n"
            "4. [ ] pending1\n5. [ ] pending2\n",
            encoding="utf-8",
        )

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"ok", None))
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc), \
             patch.object(svc, "sync_plans"):
            svc.AUTO_DONE_SCRIPT = tmp_plan_dir / "auto-done.ps1"
            (svc.AUTO_DONE_SCRIPT).write_text("# fake", encoding="utf-8")

            result = await svc.run_done(str(plan))

        assert result["remaining_tasks"] == 2
        assert result["total_tasks"] == 5
        assert result["plan_status"] == "구현중"

    @pytest.mark.asyncio
    async def test_progress_all_done(self, svc, tmp_plan_dir):
        """Boundary: 전체 완료 plan → remaining_tasks=0"""
        plan = tmp_plan_dir / "all_done.md"
        plan.write_text(
            "> 상태: 구현완료\n\n1. [x] a\n2. [x] b\n- [x] c\n",
            encoding="utf-8",
        )

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"ok", None))
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc), \
             patch.object(svc, "sync_plans"):
            svc.AUTO_DONE_SCRIPT = tmp_plan_dir / "auto-done.ps1"
            (svc.AUTO_DONE_SCRIPT).write_text("# fake", encoding="utf-8")

            result = await svc.run_done(str(plan))

        assert result["remaining_tasks"] == 0
        assert result["total_tasks"] == 3
        assert result["plan_status"] == "구현완료"

    @pytest.mark.asyncio
    async def test_progress_no_checkboxes(self, svc, tmp_plan_dir):
        """Boundary: 체크박스 없는 plan → total=0, remaining=0"""
        plan = tmp_plan_dir / "no_cb.md"
        plan.write_text("> 상태: 초안\n\nSome text only.", encoding="utf-8")

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"ok", None))
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc), \
             patch.object(svc, "sync_plans"):
            svc.AUTO_DONE_SCRIPT = tmp_plan_dir / "auto-done.ps1"
            (svc.AUTO_DONE_SCRIPT).write_text("# fake", encoding="utf-8")

            result = await svc.run_done(str(plan))

        assert result["remaining_tasks"] == 0
        assert result["total_tasks"] == 0
        assert result["plan_status"] == "초안"

    @pytest.mark.asyncio
    async def test_progress_no_status_line(self, svc, tmp_plan_dir):
        """Boundary: 상태 라인 없는 plan → plan_status='unknown'"""
        plan = tmp_plan_dir / "no_status.md"
        plan.write_text("# No status\n\n1. [ ] task\n2. [x] done\n", encoding="utf-8")

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"ok", None))
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc), \
             patch.object(svc, "sync_plans"):
            svc.AUTO_DONE_SCRIPT = tmp_plan_dir / "auto-done.ps1"
            (svc.AUTO_DONE_SCRIPT).write_text("# fake", encoding="utf-8")

            result = await svc.run_done(str(plan))

        assert result["remaining_tasks"] == 1
        assert result["total_tasks"] == 2
        assert result["plan_status"] == "unknown"

    @pytest.mark.asyncio
    async def test_progress_captured_before_execution(self, svc, tmp_plan_dir):
        """Cross-check: progress는 auto-done.ps1 실행 전 캡처됨"""
        plan = tmp_plan_dir / "pre_capture.md"
        plan.write_text("> 상태: 구현중\n\n1. [ ] task1\n2. [ ] task2\n", encoding="utf-8")

        call_order = []

        original_progress = svc.get_plan_progress

        def track_progress(path):
            call_order.append("progress")
            return original_progress(path)

        async def mock_communicate():
            call_order.append("subprocess")
            return (b"ok", None)

        mock_proc = AsyncMock()
        mock_proc.communicate = mock_communicate
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc), \
             patch.object(svc, "sync_plans"), \
             patch.object(svc, "get_plan_progress", side_effect=track_progress):
            svc.AUTO_DONE_SCRIPT = tmp_plan_dir / "auto-done.ps1"
            (svc.AUTO_DONE_SCRIPT).write_text("# fake", encoding="utf-8")

            result = await svc.run_done(str(plan))

        assert call_order.index("progress") < call_order.index("subprocess")
        assert result["remaining_tasks"] == 2
        assert result["total_tasks"] == 2

    @pytest.mark.asyncio
    async def test_nonexistent_script_has_default_progress(self, svc, tmp_plan_dir):
        """Existence: auto-done.ps1 미존재 → progress 기본값 (subprocess 전 단계에서 반환)"""
        plan = tmp_plan_dir / "test.md"
        plan.write_text("> 상태: 대기\n\n1. [ ] task", encoding="utf-8")

        svc.AUTO_DONE_SCRIPT = tmp_plan_dir / "no_script.ps1"

        result = await svc.run_done(str(plan))

        assert result["success"] is False
        assert result["remaining_tasks"] == 0
        assert result["total_tasks"] == 0
        assert result["plan_status"] == ""
