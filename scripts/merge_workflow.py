"""
MergeWorkflow — plan-runner worktree 완료 후 머지 워크플로우

실행 순서:
  1. worktree에서 변경사항 커밋
  2. main 브랜치에 머지
  3. HTTP 테스트 실행
  4. 성공 시 worktree 정리
"""
import json
import subprocess
import logging
from pathlib import Path
from dataclasses import dataclass

logger = logging.getLogger(__name__)

RUNNER_KEY_PREFIX = "plan-runner:runners"


@dataclass
class TestResult:
    passed: bool
    output: str
    exit_code: int


@dataclass
class WorkflowResult:
    merged: bool
    tests_passed: bool
    conflict: bool
    message: str


class MergeWorkflow:
    def __init__(self, project_root: Path, redis_client, python_path: str = None, workflow_manager=None):
        self.project_root = project_root
        self.redis_client = redis_client
        self.python_path = python_path or "python"
        self.workflow_manager = workflow_manager

    def _publish_log(self, runner_id: str, tag: str, message: str) -> None:
        """Redis pub/sub으로 머지 진행 로그를 SSE 스트림에 전달한다. 파일 로그에도 동시 기록."""
        logger.info(f"[MERGE][{tag}] {message}")
        try:
            self.redis_client.publish(
                f"plan-runner:merge-log:{runner_id}",
                f"[MERGE][{tag}] {message}"
            )
        except Exception:
            pass

    def _update_queue_status(self, runner_id: str, new_status: str) -> None:
        """plan-runner:merge-queue 내 해당 runner_id 항목의 status를 갱신한다."""
        try:
            items = self.redis_client.lrange("plan-runner:merge-queue", 0, -1)
            for index, raw in enumerate(items):
                try:
                    item = json.loads(raw)
                except Exception:
                    continue
                if item.get("runner_id") == runner_id:
                    item["status"] = new_status
                    self.redis_client.lset("plan-runner:merge-queue", index, json.dumps(item))
                    break
        except Exception:
            pass

    def _wf_update(self, runner_id: str, status: str, **kwargs) -> None:
        """workflow_manager가 있을 때 안전하게 상태 업데이트"""
        if not self.workflow_manager:
            return
        try:
            wf = self.workflow_manager.get_by_runner_id(runner_id)
            if wf:
                self.workflow_manager.update_status(wf["id"], status, **kwargs)
        except Exception as e:
            logger.warning(f"[MergeWorkflow._wf_update] workflow update 실패 (무시): {e}")

    def run(self, runner_id: str, worktree_path: Path, base_dir: Path, plan_file: str = None, auto_resolve: bool = True) -> WorkflowResult:
        from worktree_manager import WorktreeManager

        # Workflow: merging 상태로 전이
        self._wf_update(runner_id, "merging")

        try:
            # 1. 변경사항 커밋
            self._publish_log(runner_id, "COMMIT", "변경사항 커밋 중...")
            subprocess.run(["git", "add", "-A"], cwd=str(worktree_path), capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", f"feat: runner/{runner_id} 구현 완료"],
                cwd=str(worktree_path), capture_output=True
            )
            self._publish_log(runner_id, "COMMIT", "커밋 완료")

            # 2. 머지
            self._update_queue_status(runner_id, "merging")
            self._publish_log(runner_id, "MERGE", f"main 브랜치에 머지 중... (auto_resolve={auto_resolve})")
            merge_result = WorktreeManager.merge_to_main(runner_id, base_dir, self.project_root, plan_file=plan_file, auto_resolve=auto_resolve, redis_client=self.redis_client)
            if not merge_result.success:
                # conflict/test_failed: worktree 보존 (수동 해결 대기)
                self._publish_log(runner_id, "ERROR", f"머지 충돌: {merge_result.message[:200]}")
                self._update_queue_status(runner_id, "failed")
                if self.redis_client:
                    try:
                        self.redis_client.set(
                            f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "conflict"
                        )
                    except Exception:
                        pass
                self._wf_update(runner_id, "failed", error_message=f"머지 충돌: {merge_result.message[:500]}")
                return WorkflowResult(
                    merged=False,
                    tests_passed=False,
                    conflict=merge_result.conflict,
                    message=merge_result.message
                )
            self._publish_log(runner_id, "MERGE", "머지 성공")

            # 3. HTTP 테스트
            self._update_queue_status(runner_id, "testing")
            self._publish_log(runner_id, "TEST", "HTTP 테스트 실행 중...")
            test_result = self.run_post_merge_tests()
            if not test_result.passed:
                # conflict/test_failed: worktree 보존 (수동 해결 대기)
                self._publish_log(runner_id, "ERROR", f"테스트 실패: {test_result.output[:200]}")
                self._update_queue_status(runner_id, "failed")
                if self.redis_client:
                    try:
                        self.redis_client.set(
                            f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "test_failed"
                        )
                    except Exception:
                        pass
                self._wf_update(runner_id, "failed", error_message=f"테스트 실패: {test_result.output[:500]}")
                return WorkflowResult(
                    merged=True,
                    tests_passed=False,
                    conflict=False,
                    message=test_result.output[:500]
                )
            self._publish_log(runner_id, "TEST", "테스트 통과")

            # 머지 커밋 해시 조회
            commit_hash = ""
            try:
                result = subprocess.run(
                    ["git", "log", "-1", "--format=%H"],
                    capture_output=True, text=True, cwd=str(self.project_root)
                )
                commit_hash = result.stdout.strip()
            except Exception:
                pass

            # 4. worktree 정리
            WorktreeManager.remove(runner_id, base_dir, plan_file=plan_file)
            self._update_queue_status(runner_id, "done")
            self._publish_log(runner_id, "DONE", "worktree 정리 완료")
            self._publish_log(runner_id, "DONE", "__MERGE_COMPLETED__")
            if self.redis_client:
                try:
                    self.redis_client.set(
                        f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "merged"
                    )
                except Exception:
                    pass

            # Workflow: merged 상태로 전이
            self._wf_update(runner_id, "merged", commit_hash=commit_hash)

            return WorkflowResult(merged=True, tests_passed=True, conflict=False, message="성공")

        except Exception as e:
            self._publish_log(runner_id, "ERROR", f"예외 발생: {e}")
            self._update_queue_status(runner_id, "failed")
            if self.redis_client:
                try:
                    self.redis_client.set(
                        f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "error"
                    )
                except Exception:
                    pass
            try:
                WorktreeManager.remove(runner_id, base_dir, plan_file=plan_file)
            except Exception:
                pass
            self._wf_update(runner_id, "failed", error_message=str(e))
            return WorkflowResult(merged=False, tests_passed=False, conflict=False, message=str(e))

    def _get_project_python(self) -> str:
        """project_root의 venv Python 경로를 반환한다. 없으면 self.python_path 사용."""
        candidates = [
            self.project_root / ".venv" / "Scripts" / "python.exe",
            self.project_root / "venv" / "Scripts" / "python.exe",
            self.project_root / ".venv" / "bin" / "python",
        ]
        for candidate in candidates:
            if candidate.exists():
                return str(candidate)
        return self.python_path

    def run_post_merge_tests(self) -> TestResult:
        project_python = self._get_project_python()
        result = subprocess.run(
            [project_python, "-m", "pytest", str(self.project_root / "tests"), "-m", "http", "-v"],
            capture_output=True, text=True, cwd=str(self.project_root)
        )
        return TestResult(
            passed=result.returncode == 0,
            output=result.stdout + result.stderr,
            exit_code=result.returncode
        )
