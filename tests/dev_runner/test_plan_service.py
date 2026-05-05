"""PlanService 단위 테스트 - RIGHT-BICEP 원칙 적용

대상 소스: app/modules/dev_runner/services/plan_service.py
"""

import asyncio
import json
import pytest
from datetime import date
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

from app.modules.dev_runner.schemas import PlanProgressResponse


# ========== Fixtures ==========

@pytest.fixture
def tmp_plan_dir(tmp_path):
    """임시 plan 디렉토리"""
    plan_dir = tmp_path / "docs" / "plan"
    plan_dir.mkdir(parents=True)
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

    def test_status_impl_complete_is_ignored(self, svc, tmp_path):
        """상태가 '구현완료'인 plan → True (완료 계열 → 목록에서 숨김)"""
        path = tmp_path / "test.md"
        progress = PlanProgressResponse(done=0, total=1, percent=0)
        assert svc._is_ignored_plan(path, "구현완료", progress) is True

    def test_all_checkboxes_done_is_ignored(self, svc, tmp_path):
        """체크박스 100% 완료 plan은 자동 숨김 대상 → True"""
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
        """상태가 '검토완료'인 plan → False (검토완료 = 리뷰 완료, 구현 미시작 상태이므로 무시 대상 아님)"""
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

    def test_progress_count_RIGHT_numbered_direct(self, svc, tmp_plan_dir):
        """1. [x] 형태 번호 목록 직접 체크박스 total/done 정확성 검증"""
        content = """\
1. [x] done task
2. [ ] pending task
3. [x] another done
"""
        path = _write_plan(tmp_plan_dir, "test_numbered_direct.md", content)
        result = svc.get_plan_progress(path)

        assert result.total == 3
        assert result.done == 2
        assert result.percent == 66

    def test_progress_count_RIGHT_mixed(self, svc, tmp_plan_dir):
        """1. [x] + - [x] 혼합 형태 total/done 정확성"""
        content = """\
1. [x] numbered done
2. [ ] numbered pending
- [x] bullet done
- [ ] bullet pending
"""
        path = _write_plan(tmp_plan_dir, "test_mixed.md", content)
        result = svc.get_plan_progress(path)

        assert result.total == 4
        assert result.done == 2
        assert result.percent == 50

    def test_progress_count_BOUNDARY_nested(self, svc, tmp_plan_dir):
        """1. - [x] (번호+대시 중첩) 형태 파싱 검증"""
        content = """\
1. - [x] nested done
2. - [ ] nested pending
- [x] bullet done
"""
        path = _write_plan(tmp_plan_dir, "test_nested.md", content)
        result = svc.get_plan_progress(path)

        assert result.total == 3
        assert result.done == 2

    def test_progress_count_BOUNDARY_empty(self, svc, tmp_plan_dir):
        """체크박스 없는 content → total=0"""
        content = """\
# 체크박스 없는 문서

일반 텍스트만 존재합니다.
"""
        path = _write_plan(tmp_plan_dir, "test_empty.md", content)
        result = svc.get_plan_progress(path)

        assert result.total == 0
        assert result.done == 0
        assert result.percent == 0


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

        svc._registered_paths = [{"path": str(folder), "type": "plan"}, {"path": str(ext_plan), "type": "plan"}]

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
        svc._registered_paths = [{"path": str(folder), "type": "plan"}]

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
        svc._registered_paths = [{"path": str(folder), "type": "plan"}]

        results = svc.list_plans(include_ignored=True)
        filenames = [r.filename for r in results]

        assert "plan_a_todo.md" in filenames
        assert "plan_a.md" not in filenames

    def test_folder_shows_orphan_todo(self, svc, tmp_path):
        """메인 파일 없이 _todo.md만 있으면 독립 항목으로 표시"""
        folder = self._make_folder_with_plans(
            tmp_path, "plans_folder", ["plan_b_todo.md"]
        )
        svc._registered_paths = [{"path": str(folder), "type": "plan"}]

        results = svc.list_plans(include_ignored=True)
        filenames = [r.filename for r in results]

        assert "plan_b_todo.md" in filenames

    def test_folder_shows_main_when_no_todo(self, svc, tmp_path):
        """_todo.md가 없으면 메인 파일 그대로 표시"""
        folder = self._make_folder_with_plans(
            tmp_path, "plans_folder", ["plan_c.md"]
        )
        svc._registered_paths = [{"path": str(folder), "type": "plan"}]

        results = svc.list_plans(include_ignored=True)
        filenames = [r.filename for r in results]

        assert "plan_c.md" in filenames

    def test_nonexistent_folder_ignored(self, svc, tmp_path):
        """존재하지 않는 폴더 경로 → list_plans()에서 무시 (에러 없음)"""
        nonexistent = str(tmp_path / "does_not_exist")
        svc._registered_paths = [{"path": nonexistent, "type": "plan"}]

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

        svc._registered_paths = [{"path": str(folder), "type": "plan"}, {"path": str(single_file), "type": "plan"}]

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
        data_paths = [e["path"] if isinstance(e, dict) else e for e in data]
        assert "/some/path" in data_paths

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
        data_paths = [e["path"] if isinstance(e, dict) else e for e in data]
        for p in paths:
            assert p in data_paths

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
        data_paths = [e["path"] if isinstance(e, dict) else e for e in data]
        assert any("project-a" in p for p in data_paths)

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
        reg_paths = [e["path"] if isinstance(e, dict) else e for e in svc._registered_paths]
        assert "/existing/path" in reg_paths
        assert "/should/not/appear" not in reg_paths

    def test_normalizes_monitor_page_legacy_paths_to_plans_ssot(self, dev_runner_config_isolation, tmp_path):
        """monitor-page legacy docs/plan, docs/archive 등록 경로는 plans SSOT로 치환"""
        from app.modules.dev_runner.services.plan_service import PlanService

        cfg = dev_runner_config_isolation
        project_root = tmp_path / "monitor-page"
        reg_file = project_root / "registered_paths.json"
        legacy_plan = project_root / "docs" / "plan"
        legacy_archive = project_root / "docs" / "archive"
        ssot_plan = project_root / ".worktrees" / "plans" / "docs" / "plan"
        ssot_archive = project_root / ".worktrees" / "plans" / "docs" / "archive"

        ssot_plan.mkdir(parents=True)
        ssot_archive.mkdir(parents=True)
        reg_file.write_text(
            json.dumps(
                [
                    {"path": str(legacy_plan), "type": "plan"},
                    {"path": str(legacy_archive), "type": "archive"},
                ]
            ),
            encoding="utf-8",
        )
        cfg.REGISTERED_PATHS_FILE = reg_file
        cfg.EXTERNAL_PLANS_FILE = project_root / "external_plans.json"
        cfg.IGNORED_PLANS_FILE = project_root / "ignored_plans.json"
        cfg.WTOOLS_BASE_DIR = tmp_path / "nonexistent_wtools"
        cfg.IGNORED_PLANS_FILE.write_text("[]", encoding="utf-8")

        with patch("app.modules.dev_runner.services.plan_service.PROJECT_ROOT", project_root):
            svc = PlanService()

        reg_paths = {(entry["path"], entry["type"]) for entry in svc._registered_paths}
        assert (str(ssot_plan.resolve()), "plan") in reg_paths
        assert (str(ssot_archive.resolve()), "archive") in reg_paths
        assert (str(legacy_plan.resolve()), "plan") not in reg_paths
        assert (str(legacy_archive.resolve()), "archive") not in reg_paths


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
        """Right: Python 네이티브 done 성공 → success=True, sync 호출"""
        plan = tmp_plan_dir / "done_test.md"
        plan.write_text("> 상태: 구현완료\n\n1. [x] task", encoding="utf-8")

        with patch.object(svc, "_archive_plan", new=AsyncMock(return_value=(tmp_plan_dir / "archive" / "done_test.md", None))) as mock_arc, \
             patch.object(svc, "_update_todo_done"), \
             patch.object(svc, "_archive_done_if_needed"), \
             patch.object(svc, "_git_commit", new=AsyncMock(return_value="commit ok")), \
             patch.object(svc, "_resolve_project_dir", return_value=tmp_plan_dir), \
             patch.object(svc, "sync_plans") as mock_sync:
            result = await svc.run_done(str(plan))

        assert result["success"] is True
        assert "성공" in result["message"]
        assert result["remaining_tasks"] == 0
        assert result["total_tasks"] == 1
        assert result["plan_status"] == "구현완료"
        mock_sync.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_done_commit_nonzero_returns_failure_E(self, svc, tmp_path):
        """E: commit script non-zero는 run_done success=False로 전파된다."""
        plan_dir = tmp_path / "docs" / "plan"
        archive_dir = tmp_path / "docs" / "archive"
        plan_dir.mkdir(parents=True)
        archive_dir.mkdir(parents=True)
        plan = plan_dir / "2026-04-03-commit-fail.md"
        archive = archive_dir / plan.name
        plan.write_text("> 상태: 구현완료\n> 진행률: 1/1 (100%)\n\n- [x] task\n", encoding="utf-8")
        archive.write_text("# archived\n", encoding="utf-8")
        commit_ps1 = tmp_path / "commit.ps1"
        commit_ps1.write_text("throw 'fail'\n", encoding="utf-8")

        add_proc = AsyncMock()
        add_proc.communicate = AsyncMock(return_value=(b"add ok", None))
        add_proc.returncode = 0
        commit_proc = AsyncMock()
        commit_proc.communicate = AsyncMock(return_value=(b"commit failed hard", None))
        commit_proc.returncode = 17

        with patch.object(type(svc), "COMMIT_PS1", commit_ps1), \
             patch.object(type(svc), "COMMIT_SH", tmp_path / "missing-commit.sh"), \
             patch("app.modules.dev_runner.services.git_commit_roots._has_staged_changes", return_value=True), \
             patch("app.modules.dev_runner.services.git_commit_roots.asyncio.create_subprocess_exec", side_effect=[add_proc, commit_proc]), \
             patch.object(svc, "_archive_plan", new=AsyncMock(return_value=(archive, None))), \
             patch.object(svc, "_update_todo_done"), \
             patch.object(svc, "_archive_done_if_needed", return_value=None), \
             patch.object(svc, "_resolve_project_dir", return_value=tmp_path), \
             patch.object(svc, "sync_plans"):
            result = await svc.run_done(str(plan))

        assert result["success"] is False
        assert "commit script failed (17)" in result["message"]
        assert "commit failed hard" in result["message"]

    @pytest.mark.asyncio
    async def test_failure_returns_false(self, svc, tmp_plan_dir):
        """Inverse: _archive_plan 예외 → success=False"""
        plan = tmp_plan_dir / "fail_test.md"
        plan.write_text("> 상태: 구현완료\n\n1. [x] task\n2. [ ] pending", encoding="utf-8")

        with patch.object(svc, "_archive_plan", side_effect=OSError("archive failed")):
            result = await svc.run_done(str(plan))

        assert result["success"] is False
        assert "archive failed" in result["message"]
        assert result["remaining_tasks"] == 0
        assert result["total_tasks"] == 0

    @pytest.mark.asyncio
    async def test_runner_ownership_guard_blocks_pre_dirty_source(self, svc, tmp_path):
        """R: run 시작 시 dirty였던 plan source path는 auto-done에서 차단된다."""
        plan_dir = tmp_path / "docs" / "plan"
        plan_dir.mkdir(parents=True)
        (tmp_path / "docs").mkdir(exist_ok=True)
        ownership_dir = tmp_path / "logs" / "dev_runner" / "ownership"
        ownership_dir.mkdir(parents=True, exist_ok=True)

        plan = plan_dir / "2026-04-14_ownership-block.md"
        plan.write_text("> 상태: 구현완료\n> 진행률: 2/2 (100%)\n\n- [x] a\n- [x] b\n", encoding="utf-8")
        (ownership_dir / "runner-1.json").write_text(
            json.dumps(
                {
                    "runner_id": "runner-1",
                    "captured_at": "2026-04-14T16:54:00",
                    "project_root": str(tmp_path),
                    "dirty_files": ["docs/plan/2026-04-14_ownership-block.md"],
                    "owned_files": [],
                    "clean_at_start_files": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        with patch.object(type(svc), "_ownership_snapshot_dir", return_value=ownership_dir), \
             patch.object(svc, "_archive_plan", new=AsyncMock(return_value=(tmp_path / "docs" / "archive" / "ownership_block.md", None))) as mock_archive:
            result = await svc.run_done(str(plan), runner_id="runner-1")

        assert result["success"] is False
        assert result["reason"] == "ownership_guard"
        assert "pre-dirty file" in result["message"]
        mock_archive.assert_not_called()
        assert plan.exists(), "ownership guard 차단 시 원본 plan은 유지되어야 함"

    @pytest.mark.asyncio
    async def test_runner_ownership_guard_blocks_pre_dirty_history_archive(self, svc, tmp_path):
        """R: run 시작 시 dirty였던 DONE history archive도 auto-done에서 차단된다."""
        plan_dir = tmp_path / "docs" / "plan"
        plan_dir.mkdir(parents=True)
        (tmp_path / "docs").mkdir(exist_ok=True)
        ownership_dir = tmp_path / "logs" / "dev_runner" / "ownership"
        ownership_dir.mkdir(parents=True, exist_ok=True)
        today = date.today()
        history_name = f"DONE-{today.year}-W{today.isocalendar()[1]:02d}.md"

        plan = plan_dir / "2026-04-14_history-block.md"
        plan.write_text("> 상태: 구현완료\n> 진행률: 1/1 (100%)\n\n- [x] a\n", encoding="utf-8")
        (ownership_dir / "runner-2.json").write_text(
            json.dumps(
                {
                    "runner_id": "runner-2",
                    "captured_at": "2026-04-14T16:54:00",
                    "project_root": str(tmp_path),
                    "dirty_files": [f".worktrees/plans/docs/history/{history_name}"],
                    "owned_files": [],
                    "clean_at_start_files": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        with patch.object(type(svc), "_ownership_snapshot_dir", return_value=ownership_dir), \
             patch.object(svc, "_archive_plan", new=AsyncMock(return_value=(tmp_path / "docs" / "archive" / "history_block.md", None))) as mock_archive:
            result = await svc.run_done(str(plan), runner_id="runner-2")

        assert result["success"] is False
        assert result["reason"] == "ownership_guard"
        assert history_name in result["message"]
        mock_archive.assert_not_called()
        assert plan.exists(), "ownership guard 차단 시 원본 plan은 유지되어야 함"

    @pytest.mark.asyncio
    async def test_runner_ownership_guard_blocks_unowned_targets(self, svc, tmp_path):
        """R: snapshot owned_files 바깥의 auto-done 대상은 차단된다."""
        plan_dir = tmp_path / "docs" / "plan"
        plan_dir.mkdir(parents=True)
        docs_dir = tmp_path / ".worktrees" / "plans" / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)
        ownership_dir = tmp_path / "logs" / "dev_runner" / "ownership"
        ownership_dir.mkdir(parents=True, exist_ok=True)
        (tmp_path / ".worktrees" / "plans" / "TODO.md").write_text("# TODO\n\n## In Progress\n\n## Pending\n", encoding="utf-8")
        (docs_dir / "DONE.md").write_text("# DONE\n", encoding="utf-8")

        plan = plan_dir / "2026-04-14_owned-only.md"
        plan.write_text("> 상태: 구현완료\n> 진행률: 1/1 (100%)\n\n- [x] a\n", encoding="utf-8")
        (ownership_dir / "runner-3.json").write_text(
            json.dumps(
                {
                    "runner_id": "runner-3",
                    "captured_at": "2026-04-14T16:54:00",
                    "project_root": str(tmp_path),
                    "dirty_files": [],
                    "owned_files": [
                        "docs/plan/2026-04-14_owned-only.md",
                        "docs/archive/2026-04-14_owned-only.md",
                    ],
                    "clean_at_start_files": [
                        "docs/plan/2026-04-14_owned-only.md",
                        "docs/archive/2026-04-14_owned-only.md",
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        with patch.object(type(svc), "_ownership_snapshot_dir", return_value=ownership_dir), \
             patch.object(svc, "_archive_plan", new=AsyncMock(return_value=(tmp_path / "docs" / "archive" / "owned_only.md", None))) as mock_archive:
            result = await svc.run_done(str(plan), runner_id="runner-3")

        assert result["success"] is False
        assert result["reason"] == "ownership_guard"
        assert "unowned file" in result["message"]
        mock_archive.assert_not_called()
        assert plan.exists(), "ownership guard 차단 시 원본 plan은 유지되어야 함"

    @pytest.mark.asyncio
    async def test_run_done_manual_path_ignores_runner_snapshot(self, svc, tmp_path):
        """B: runner_id=None 수동 done 경로는 snapshot 존재와 무관하게 ownership guard를 타지 않는다."""
        plan_dir = tmp_path / "docs" / "plan"
        plan_dir.mkdir(parents=True)
        docs_dir = tmp_path / ".worktrees" / "plans" / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)
        ownership_dir = tmp_path / "logs" / "dev_runner" / "ownership"
        ownership_dir.mkdir(parents=True, exist_ok=True)
        (tmp_path / ".worktrees" / "plans" / "TODO.md").write_text("# TODO\n\n## In Progress\n\n## Pending\n", encoding="utf-8")
        (docs_dir / "DONE.md").write_text("# DONE\n", encoding="utf-8")

        plan = plan_dir / "2026-04-14_manual-done.md"
        plan.write_text("> 상태: 구현완료\n> 진행률: 1/1 (100%)\n\n- [x] a\n", encoding="utf-8")
        (ownership_dir / "runner-manual.json").write_text(
            json.dumps(
                {
                    "runner_id": "runner-manual",
                    "captured_at": "2026-04-14T16:54:00",
                    "project_root": str(tmp_path),
                    "dirty_files": ["TODO.md", "docs/DONE.md"],
                    "owned_files": [],
                    "clean_at_start_files": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        archive_path = tmp_path / "docs" / "archive" / "manual-done.md"
        with patch.object(type(svc), "_ownership_snapshot_dir", return_value=ownership_dir), \
             patch.object(svc, "_archive_plan", new=AsyncMock(return_value=(archive_path, None))), \
             patch.object(svc, "_git_commit", new=AsyncMock(return_value="commit ok")), \
             patch.object(svc, "sync_plans"):
            result = await svc.run_done(str(plan))

        assert result["success"] is True
        assert result.get("reason") != "ownership_guard"

    @pytest.mark.asyncio
    async def test_run_done_residue_guard_returns_failure_R(self, svc, tmp_path):
        """R: auto path는 snapshot 밖 stray dirty가 있으면 residue_guard로 차단된다."""
        plan_dir = tmp_path / "docs" / "plan"
        plan_dir.mkdir(parents=True)
        docs_dir = tmp_path / ".worktrees" / "plans" / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)
        ownership_dir = tmp_path / "logs" / "dev_runner" / "ownership"
        ownership_dir.mkdir(parents=True, exist_ok=True)
        (tmp_path / ".git").write_text("gitdir: mock\n", encoding="utf-8")
        (tmp_path / ".worktrees" / "plans" / "TODO.md").write_text("# TODO\n\n## In Progress\n\n## Pending\n", encoding="utf-8")
        (docs_dir / "DONE.md").write_text("# DONE\n", encoding="utf-8")

        plan = plan_dir / "2026-04-21_residue-guard.md"
        plan.write_text("> 상태: 구현완료\n> 진행률: 1/1 (100%)\n\n- [x] a\n", encoding="utf-8")
        (ownership_dir / "runner-residue.json").write_text(
            json.dumps(
                {
                    "runner_id": "runner-residue",
                    "captured_at": "2026-04-21T10:00:00",
                    "project_root": str(tmp_path),
                    "dirty_files": [],
                    "owned_files": [],
                    "clean_at_start_files": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        with patch.object(type(svc), "_ownership_snapshot_dir", return_value=ownership_dir), \
             patch.object(type(svc), "_collect_current_dirty_keys", return_value={"app/stray.py"}), \
             patch.object(svc, "_archive_plan", new=AsyncMock(return_value=(tmp_path / "docs" / "archive" / "residue.md", None))) as mock_archive:
            result = await svc.run_done(str(plan), runner_id="runner-residue")

        assert result["success"] is False
        assert result["reason"] == "residue_guard"
        assert "app/stray.py" in result["message"]
        mock_archive.assert_not_called()

    @pytest.mark.asyncio
    async def test_run_done_residue_guard_empty_tree_passes_B(self, svc, tmp_path):
        """B: current dirty가 비어 있으면 residue_guard 없이 기존 완료 경로를 유지한다."""
        plan_dir = tmp_path / "docs" / "plan"
        plan_dir.mkdir(parents=True)
        docs_dir = tmp_path / ".worktrees" / "plans" / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)
        ownership_dir = tmp_path / "logs" / "dev_runner" / "ownership"
        ownership_dir.mkdir(parents=True, exist_ok=True)
        (tmp_path / ".git").write_text("gitdir: mock\n", encoding="utf-8")
        (tmp_path / ".worktrees" / "plans" / "TODO.md").write_text("# TODO\n\n## In Progress\n\n## Pending\n", encoding="utf-8")
        (docs_dir / "DONE.md").write_text("# DONE\n", encoding="utf-8")

        plan = plan_dir / "2026-04-21_residue-clean.md"
        plan.write_text("> 상태: 구현완료\n> 진행률: 1/1 (100%)\n\n- [x] a\n", encoding="utf-8")
        (ownership_dir / "runner-clean.json").write_text(
            json.dumps(
                {
                    "runner_id": "runner-clean",
                    "captured_at": "2026-04-21T10:00:00",
                    "project_root": str(tmp_path),
                    "dirty_files": [],
                    "owned_files": [],
                    "clean_at_start_files": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        archive_path = tmp_path / "docs" / "archive" / "residue-clean.md"
        with patch.object(type(svc), "_ownership_snapshot_dir", return_value=ownership_dir), \
             patch.object(type(svc), "_collect_current_dirty_keys", return_value=set()), \
             patch.object(svc, "_archive_plan", new=AsyncMock(return_value=(archive_path, None))), \
             patch.object(svc, "_git_commit", new=AsyncMock(return_value="commit ok")), \
             patch.object(svc, "sync_plans"):
            result = await svc.run_done(str(plan), runner_id="runner-clean")

        assert result["success"] is True
        assert result.get("reason") != "residue_guard"

    @pytest.mark.asyncio
    async def test_run_done_residue_guard_missing_snapshot_E(self, svc, tmp_path):
        """E: snapshot 부재 시 residue_guard가 strict fail 한다."""
        plan_dir = tmp_path / "docs" / "plan"
        plan_dir.mkdir(parents=True)
        docs_dir = tmp_path / ".worktrees" / "plans" / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)
        ownership_dir = tmp_path / "logs" / "dev_runner" / "ownership"
        ownership_dir.mkdir(parents=True, exist_ok=True)
        (tmp_path / ".git").write_text("gitdir: mock\n", encoding="utf-8")
        (tmp_path / ".worktrees" / "plans" / "TODO.md").write_text("# TODO\n\n## In Progress\n\n## Pending\n", encoding="utf-8")
        (docs_dir / "DONE.md").write_text("# DONE\n", encoding="utf-8")

        plan = plan_dir / "2026-04-21_residue-missing-snapshot.md"
        plan.write_text("> 상태: 구현완료\n> 진행률: 1/1 (100%)\n\n- [x] a\n", encoding="utf-8")

        with patch.object(type(svc), "_ownership_snapshot_dir", return_value=ownership_dir), \
             patch.object(svc, "_archive_plan", new=AsyncMock(return_value=(tmp_path / "docs" / "archive" / "residue-missing.md", None))) as mock_archive:
            result = await svc.run_done(str(plan), runner_id="runner-missing")

        assert result["success"] is False
        assert result["reason"] == "residue_guard"
        assert "snapshot not found" in result["message"]
        mock_archive.assert_not_called()

    @pytest.mark.asyncio
    async def test_run_done_commits_done_history_archive_when_done_overflows(self, svc, tmp_path):
        """R: DONE.md가 5개를 넘으면 history archive도 commit 대상에 포함된다."""
        plan_dir = tmp_path / "docs" / "plan"
        plan_dir.mkdir(parents=True)
        docs_dir = tmp_path / ".worktrees" / "plans" / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)
        done_path = docs_dir / "DONE.md"
        done_path.write_text(
            "# DONE\n\n"
            "- [x] 2026-04-01: a\n"
            "- [x] 2026-04-02: b\n"
            "- [x] 2026-04-03: c\n"
            "- [x] 2026-04-04: d\n"
            "- [x] 2026-04-05: e\n",
            encoding="utf-8",
        )

        plan = plan_dir / "2026-04-14_history-archive.md"
        plan.write_text(
            "# feat: history archive\n\n"
            "> 상태: 구현완료\n"
            "> 진행률: 1/1 (100%)\n\n"
            "- [x] only\n",
            encoding="utf-8",
        )

        with patch.object(svc, "_archive_plan", new=AsyncMock(return_value=(tmp_path / "docs" / "archive" / "history_archive.md", None))), \
             patch.object(svc, "_resolve_project_dir", return_value=tmp_path), \
             patch.object(svc, "sync_plans"), \
             patch.object(svc, "_git_commit", new=AsyncMock(return_value="commit ok")) as mock_commit:
            result = await svc.run_done(str(plan))

        assert result["success"] is True
        today = date.today()
        expected_history = tmp_path / ".worktrees" / "plans" / "docs" / "history" / f"DONE-{today.year}-W{today.isocalendar()[1]:02d}.md"
        assert expected_history.exists()
        commit_files = mock_commit.await_args.args[1]
        assert expected_history in commit_files

    @pytest.mark.asyncio
    async def test_resolver_error_failure_message(self, svc, tmp_plan_dir):
        """Inverse: resolver 실패 메시지가 run_done 실패 응답에 노출된다."""
        plan = tmp_plan_dir / "resolver_fail.md"
        plan.write_text("> 상태: 구현완료\n\n1. [x] task", encoding="utf-8")

        with patch.object(
            svc,
            "_archive_plan",
            side_effect=ValueError("archive target resolve failed: source=/x rule=resolve_plan_target reason=invalid"),
        ):
            result = await svc.run_done(str(plan))

        assert result["success"] is False
        assert "archive target resolve failed" in result["message"]

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
    async def test_exception_during_archive(self, svc, tmp_plan_dir):
        """Existence: _archive_plan 오류 → success=False, error message 포함"""
        plan = tmp_plan_dir / "test.md"
        plan.write_text("content", encoding="utf-8")

        with patch.object(svc, "_archive_plan", side_effect=PermissionError("access denied")):
            result = await svc.run_done(str(plan))

        assert result["success"] is False
        assert "access denied" in result["message"]

    @pytest.mark.asyncio
    async def test_timeout_handling(self, svc, tmp_plan_dir):
        """Time: git commit 타임아웃 → 예외로 처리, success=False"""
        plan = tmp_plan_dir / "timeout_test.md"
        plan.write_text("content", encoding="utf-8")

        with patch.object(svc, "_archive_plan", new=AsyncMock(return_value=(tmp_plan_dir / "archive.md", None))), \
             patch.object(svc, "_update_todo_done"), \
             patch.object(svc, "_archive_done_if_needed"), \
             patch.object(svc, "_resolve_project_dir", return_value=tmp_plan_dir), \
             patch.object(svc, "_git_commit", new=AsyncMock(side_effect=asyncio.TimeoutError("timeout"))):
            result = await svc.run_done(str(plan))

        assert result["success"] is False
        assert result["remaining_tasks"] == 0

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

        with patch.object(svc, "_archive_plan", side_effect=RuntimeError("fail")), \
             patch.object(svc, "sync_plans") as mock_sync:
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
    async def test_failure_has_default_progress(self, svc, tmp_plan_dir):
        """Existence: 예외 발생 시 remaining/total/plan_status 기본값 반환"""
        plan = tmp_plan_dir / "test.md"
        plan.write_text("> 상태: 대기\n\n1. [ ] task", encoding="utf-8")

        with patch.object(svc, "_archive_plan", side_effect=IOError("io error")):
            result = await svc.run_done(str(plan))

        assert result["success"] is False
        assert result["remaining_tasks"] == 0
        assert result["total_tasks"] == 0
        assert result["plan_status"] == ""


# ========== batch_done Redis publish 테스트 ==========

class TestBatchDoneRedisPublish:
    """batch_done() Redis publish 검증"""

    @pytest.fixture
    def svc(self, tmp_plan_dir):
        from app.modules.dev_runner.services.plan_service import PlanService
        s = PlanService.__new__(PlanService)
        s._registered_paths = [{"path": str(tmp_plan_dir), "type": "plan"}]
        s._ignored_plans = []
        s._cache = {}
        s._plans_cache_with_ignored = None
        return s

    @pytest.fixture
    def tmp_plan_dir(self, tmp_path):
        d = tmp_path / "plan"
        d.mkdir()
        return d

    @pytest.mark.asyncio
    async def test_batch_done_publishes_plan_list_and_events(self, svc, tmp_plan_dir):
        """batch_done: PLAN_LIST, PLAN_START, PLAN_DONE 순서대로 publish"""
        # 완료 가능한 plan 2개 생성 (모든 체크박스 완료 상태)
        p1 = tmp_plan_dir / "plan-a.md"
        p2 = tmp_plan_dir / "plan-b.md"
        p1.write_text("> 상태: 검토완료\n\n- [x] task1\n", encoding="utf-8")
        p2.write_text("> 상태: 검토완료\n\n- [x] task1\n", encoding="utf-8")

        published = []

        import app.modules.dev_runner.services.plan_service as ps_module

        def fake_publish(tag, message):
            published.append((tag, message))

        with patch.object(ps_module, "_publish_log", side_effect=fake_publish), \
             patch.object(svc, "run_done", new=AsyncMock(return_value={"success": True, "message": "ok", "remaining_tasks": 0, "total_tasks": 1, "plan_status": "완료"})):

            result = await svc.batch_done()

        assert result["total"] == 2
        assert result["success"] == 2

        tags = [t for t, _ in published]
        messages = [m for _, m in published]

        # PLAN_LIST 첫 번째 publish
        assert tags[0] == "BATCH"
        assert messages[0].startswith("PLAN_LIST ")
        assert "plan-a.md" in messages[0]
        assert "plan-b.md" in messages[0]

        # PLAN_START, PLAN_DONE 쌍이 2번 나와야 함
        assert tags.count("BATCH") >= 5  # PLAN_LIST + 2*PLAN_START + 2*PLAN_DONE

        # 최종 INFO 요약
        assert "INFO" in tags
        assert any("성공" in m for _, m in published if _ == "INFO" or True)

    @pytest.mark.asyncio
    async def test_batch_done_no_targets_no_publish(self, svc, tmp_plan_dir):
        """batch_done: 대상 0개일 때 publish 미호출"""
        import app.modules.dev_runner.services.plan_service as ps_module

        published = []
        with patch.object(ps_module, "_publish_log", side_effect=lambda t, m: published.append((t, m))):
            result = await svc.batch_done()

        assert result["total"] == 0
        assert published == []

    @pytest.mark.asyncio
    async def test_batch_done_failure_publishes_error(self, svc, tmp_plan_dir):
        """batch_done: run_done 실패 시 ERROR 태그로 publish"""
        p1 = tmp_plan_dir / "plan-fail.md"
        p1.write_text("> 상태: 검토완료\n\n- [x] task\n", encoding="utf-8")

        import app.modules.dev_runner.services.plan_service as ps_module
        published = []

        with patch.object(ps_module, "_publish_log", side_effect=lambda t, m: published.append((t, m))), \
             patch.object(svc, "run_done", new=AsyncMock(return_value={"success": False, "message": "스크립트 오류", "remaining_tasks": 0, "total_tasks": 1, "plan_status": ""})):

            result = await svc.batch_done()

        assert result["failed"] == 1
        error_tags = [t for t, _ in published if t == "ERROR"]
        assert len(error_tags) >= 1
        error_messages = [m for t, m in published if t == "ERROR"]
        assert any("스크립트 오류" in m for m in error_messages)

    @pytest.mark.asyncio
    async def test_batch_done_calls_run_done_without_runner_id(self, svc, tmp_plan_dir):
        """B: ownership snapshot 존재와 무관하게 batch_done은 manual run_done(None) 경로를 사용한다."""
        p1 = tmp_plan_dir / "plan-batch.md"
        p1.write_text("> 상태: 검토완료\n\n- [x] task\n", encoding="utf-8")

        import app.modules.dev_runner.services.plan_service as ps_module

        with patch.object(ps_module, "_publish_log"), \
             patch.object(svc, "run_done", new=AsyncMock(return_value={"success": True, "message": "ok", "remaining_tasks": 0, "total_tasks": 1, "plan_status": "완료"})) as mock_run_done:
            result = await svc.batch_done()

        assert result["success"] == 1
        mock_run_done.assert_awaited_once()
        assert mock_run_done.await_args.args == (str(p1),)
        assert mock_run_done.await_args.kwargs == {}


class TestUpdatePlanStatus:
    """update_plan_status() 메서드 테스트"""

    @pytest.fixture
    def svc(self):
        from app.modules.dev_runner.services.plan_service import PlanService
        return PlanService()

    def test_replace_existing_status(self, svc, tmp_path):
        """기존 > 상태: 라인 교체"""
        f = tmp_path / "plan.md"
        f.write_text("> 상태: 초안\n\n# 제목\n", encoding="utf-8")
        result = svc.update_plan_status(str(f), "구현중")
        assert result == "구현중"
        assert "> 상태: 구현중" in f.read_text(encoding="utf-8")

    def test_insert_status_after_title(self, svc, tmp_path):
        """> 상태: 없을 때 첫 번째 # 제목 다음에 삽입"""
        f = tmp_path / "plan.md"
        f.write_text("# 제목\n\n내용\n", encoding="utf-8")
        result = svc.update_plan_status(str(f), "보류")
        assert result == "보류"
        lines = f.read_text(encoding="utf-8").splitlines()
        assert lines[0] == "# 제목"
        assert lines[1] == "> 상태: 보류"

    def test_invalid_status_raises_value_error(self, svc, tmp_path):
        """허용되지 않은 상태 → ValueError"""
        import pytest
        f = tmp_path / "plan.md"
        f.write_text("> 상태: 초안\n", encoding="utf-8")
        with pytest.raises(ValueError):
            svc.update_plan_status(str(f), "잘못된상태")

    def test_file_not_found_raises(self, svc, tmp_path):
        """파일 없음 → FileNotFoundError"""
        import pytest
        with pytest.raises(FileNotFoundError):
            svc.update_plan_status(str(tmp_path / "missing.md"), "초안")


# ========== _can_done() ==========

class TestCanDone:

    def _make_plan(self, path: str, status: str = "초안", progress=None):
        from app.modules.dev_runner.schemas import PlanFileResponse
        return PlanFileResponse(path=path, filename="plan.md", status=status, progress=progress)

    def test__can_done_with_none_progress(self, svc, tmp_path):
        """progress=None인 PlanFileResponse → lazy 파싱 후 에러 없이 동작"""
        content = "# 테스트\n\n- [x] 완료 항목\n"
        f = tmp_path / "plan.md"
        f.write_text(content, encoding="utf-8")
        plan = self._make_plan(str(f), progress=None)
        # AttributeError 없이 bool 반환
        result = svc._can_done(plan)
        assert isinstance(result, bool)

    def test__can_done_with_all_completed(self, svc, tmp_path):
        """모든 체크박스 완료 시 True 반환"""
        from app.modules.dev_runner.schemas import PlanProgressResponse
        f = tmp_path / "plan.md"
        f.write_text("# 테스트\n", encoding="utf-8")
        progress = PlanProgressResponse(done=3, total=3, percent=100)
        plan = self._make_plan(str(f), progress=progress)
        assert svc._can_done(plan) is True

    def test__can_done_with_zero_total(self, svc, tmp_path):
        """체크박스 없는 문서 → True 반환"""
        from app.modules.dev_runner.schemas import PlanProgressResponse
        f = tmp_path / "plan.md"
        f.write_text("# 분석 보고서\n내용만 있고 체크박스 없음\n", encoding="utf-8")
        progress = PlanProgressResponse(done=0, total=0, percent=0)
        plan = self._make_plan(str(f), progress=progress)
        assert svc._can_done(plan) is True


# -------------------------------------------------------------
# TC: _resolve_source -- plans worktree 경로 오분류 방지
# -------------------------------------------------------------

class TestResolveSourcePlansWorktree:
    '''PlanService._resolve_source plans worktree 경로 처리 검증'''

    @pytest.fixture
    def svc(self, dev_runner_config_isolation):
        from app.modules.dev_runner.services.plan_service import PlanService
        return PlanService()

    def test_resolve_source_plans_worktree_returns_project_name_not_plans(self, tmp_path, svc):
        '''R: .../monitor-page/.worktrees/plans/docs/plan -> monitor-page 반환 (plans 오분류 차단).'''
        plans_dir = tmp_path / 'monitor-page' / '.worktrees' / 'plans' / 'docs' / 'plan'
        plans_dir.mkdir(parents=True)

        result = svc._resolve_source(plans_dir)

        assert result == 'monitor-page', (
            f'plans worktree 경로에서 _resolve_source()는 monitor-page를 반환해야 함, 실제: {result!r}'
        )
        assert result != 'plans', (
            f'_resolve_source()가 plans를 반환하면 안 됨 (오분류): {result!r}'
        )

    def test_resolve_source_normal_docs_plan(self, tmp_path, svc):
        '''R: .../my-project/docs/plan -> my-project 반환 (기존 동작 회귀 방어).'''
        docs_plan = tmp_path / 'my-project' / 'docs' / 'plan'
        docs_plan.mkdir(parents=True)

        result = svc._resolve_source(docs_plan)

        assert result == 'my-project', (
            f'일반 docs/plan 경로에서 my-project 반환해야 함, 실제: {result!r}'
        )

    def test_resolve_source_common_docs_plan(self, tmp_path, svc):
        '''R: .../common/docs/plan -> common 반환 (기존 동작 회귀 방어).'''
        docs_plan = tmp_path / 'common' / 'docs' / 'plan'
        docs_plan.mkdir(parents=True)

        result = svc._resolve_source(docs_plan)

        assert result == 'common', (
            f'common/docs/plan 경로에서 common 반환해야 함, 실제: {result!r}'
        )
