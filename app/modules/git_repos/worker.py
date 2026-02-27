"""Git Repository 비동기 워커.

Redis 큐(git_repos:tasks)에서 작업을 소비하여
GitCommandService/GitRepoService를 호출하고
결과를 Redis에 저장합니다.
"""
import json
import logging
from datetime import datetime
from typing import Optional

from app.shared.worker.base_worker import BaseWorker
from app.shared.redis.client import RedisClient
from app.shared.redis.queue import RedisQueue, GIT_REPOS_TASK_QUEUE

logger = logging.getLogger(__name__)


class GitRepoWorker(BaseWorker):
    """Git Repository 작업 큐 워커.

    Redis 큐(git_repos:tasks)를 polling하여
    stage, commit, push, pull 등 git 작업을 비동기 처리합니다.
    """

    def __init__(self):
        super().__init__("git_repo_worker", browser_manager=None)
        self._redis_client = None
        self._redis_queue: Optional[RedisQueue] = None
        self._redis_initialized = False

    async def _setup_redis(self):
        """Redis 클라이언트 및 큐 초기화 (lazy)."""
        if self._redis_initialized:
            return

        client = await RedisClient.get_client()
        if client is None:
            logger.warning("[git_repo_worker] Redis 미연결 — git 작업 큐 비활성화")
            return

        self._redis_client = client
        self._redis_queue = RedisQueue(client, GIT_REPOS_TASK_QUEUE)
        self._redis_initialized = True
        logger.info("[git_repo_worker] Redis 연결 완료, 큐 준비됨")

    def _get_loop_interval(self) -> float:
        """Redis 연결 시 0.1초, 미연결 시 1.0초."""
        return 0.1 if self._redis_initialized else 1.0

    async def _main_loop_iteration(self):
        """메인 루프 한 사이클."""
        await self._setup_redis()
        if not self._redis_initialized:
            return
        await self._safe_execute("process_git_queue", self._process_git_queue)

    # ─────────────────────────────────────────────
    # 큐 처리
    # ─────────────────────────────────────────────

    async def _process_git_queue(self):
        """큐에서 작업 하나를 꺼내 처리."""
        task = await self._redis_queue.pop_nowait()
        if task is None:
            return

        task_id = task.get("task_id", "unknown")
        action = task.get("action", "")
        repo_id = task.get("repo_id")
        params = task.get("params", {})

        logger.info(f"[git_repo_worker] 작업 처리: task_id={task_id}, action={action}, repo_id={repo_id}")

        try:
            result = await self._dispatch_action(task_id, action, repo_id, params)
            await self._store_result(task_id, "completed", result)
        except Exception as e:
            logger.error(f"[git_repo_worker] 작업 실패: task_id={task_id}, error={e}", exc_info=True)
            await self._store_result(task_id, "failed", {"success": False, "stderr": str(e)})

    async def _dispatch_action(self, task_id: str, action: str, repo_id: Optional[int], params: dict) -> dict:
        """action 문자열에 따라 적절한 _do_*() 메서드로 분기."""
        dispatch_map = {
            "commit": self._do_commit,
            "push": self._do_push,
            "pull": self._do_pull,
            "fetch": self._do_fetch,
            "stage": self._do_stage,
            "unstage": self._do_unstage,
            "stash": self._do_stash,
            "stash-pop": self._do_stash_pop,
            "refresh": self._do_refresh,
            "refresh-all": self._do_refresh_all,
            "batch-commit": self._do_batch_commit,
            "batch-push": self._do_batch_push,
            "generate-message": self._do_generate_message,
        }

        handler = dispatch_map.get(action)
        if handler is None:
            logger.error(f"[git_repo_worker] 알 수 없는 action: {action}")
            return {"success": False, "stderr": f"알 수 없는 action: {action}"}

        return await handler(repo_id, params)

    async def _store_result(self, task_id: str, status: str, result: dict):
        """Redis에 결과를 String 키로 저장 (TTL 300초)."""
        if self._redis_client is None:
            return
        payload = {
            "task_id": task_id,
            "status": status,
            "result": result,
            "completed_at": datetime.now().isoformat(),
        }
        key = f"git_repos:result:{task_id}"
        try:
            await self._redis_client.set(key, json.dumps(payload), ex=300)
        except Exception as e:
            logger.error(f"[git_repo_worker] 결과 저장 실패: task_id={task_id}, error={e}")

    # ─────────────────────────────────────────────
    # 각 action 구현
    # ─────────────────────────────────────────────

    async def _do_commit(self, repo_id: Optional[int], params: dict) -> dict:
        from app.core.database import SessionLocal
        from app.modules.git_repos.services.repo_service import GitRepoService

        db = SessionLocal()
        try:
            svc = GitRepoService()
            repo = svc.get_repo(db, repo_id)
            if not repo:
                return {"success": False, "stderr": "레포지토리를 찾을 수 없습니다."}
            message = params.get("message", "")
            stage_all = params.get("stage_all", False)
            result = await svc.commit_repo(db, repo, message, stage_all)
            return {"success": result.success, "stdout": result.stdout, "stderr": result.stderr}
        finally:
            db.close()

    async def _do_push(self, repo_id: Optional[int], params: dict) -> dict:
        from app.core.database import SessionLocal
        from app.modules.git_repos.services.repo_service import GitRepoService

        db = SessionLocal()
        try:
            svc = GitRepoService()
            repo = svc.get_repo(db, repo_id)
            if not repo:
                return {"success": False, "stderr": "레포지토리를 찾을 수 없습니다."}
            result = await svc.smart_push_repo(db, repo)
            return {"success": result.success, "stdout": result.stdout, "stderr": result.stderr}
        finally:
            db.close()

    async def _do_pull(self, repo_id: Optional[int], params: dict) -> dict:
        from app.core.database import SessionLocal
        from app.modules.git_repos.services.repo_service import GitRepoService

        db = SessionLocal()
        try:
            svc = GitRepoService()
            repo = svc.get_repo(db, repo_id)
            if not repo:
                return {"success": False, "stderr": "레포지토리를 찾을 수 없습니다."}
            result = await svc.pull_repo(db, repo)
            return {"success": result.success, "stdout": result.stdout, "stderr": result.stderr}
        finally:
            db.close()

    async def _do_fetch(self, repo_id: Optional[int], params: dict) -> dict:
        from app.core.database import SessionLocal
        from app.modules.git_repos.services.repo_service import GitRepoService

        db = SessionLocal()
        try:
            svc = GitRepoService()
            repo = svc.get_repo(db, repo_id)
            if not repo:
                return {"success": False, "stderr": "레포지토리를 찾을 수 없습니다."}
            result = await svc.fetch_repo(db, repo)
            return {"success": result.success, "stdout": result.stdout, "stderr": result.stderr}
        finally:
            db.close()

    async def _do_stage(self, repo_id: Optional[int], params: dict) -> dict:
        from app.core.database import SessionLocal
        from app.modules.git_repos.services.repo_service import GitRepoService
        from app.modules.git_repos.services.git_command import GitCommandService

        db = SessionLocal()
        try:
            svc = GitRepoService()
            repo = svc.get_repo(db, repo_id)
            if not repo:
                return {"success": False, "stderr": "레포지토리를 찾을 수 없습니다."}
            git = GitCommandService()
            files = params.get("files", [])
            ok, stdout, stderr = await git.stage_files(repo.path, files)
            svc.log_operation(db, repo.id, "stage", "success" if ok else "failure", None, stderr or stdout)
            return {"success": ok, "stdout": stdout, "stderr": stderr}
        finally:
            db.close()

    async def _do_unstage(self, repo_id: Optional[int], params: dict) -> dict:
        from app.core.database import SessionLocal
        from app.modules.git_repos.services.repo_service import GitRepoService
        from app.modules.git_repos.services.git_command import GitCommandService

        db = SessionLocal()
        try:
            svc = GitRepoService()
            repo = svc.get_repo(db, repo_id)
            if not repo:
                return {"success": False, "stderr": "레포지토리를 찾을 수 없습니다."}
            git = GitCommandService()
            files = params.get("files", [])
            ok, stdout, stderr = await git.unstage_files(repo.path, files)
            svc.log_operation(db, repo.id, "unstage", "success" if ok else "failure", None, stderr or stdout)
            return {"success": ok, "stdout": stdout, "stderr": stderr}
        finally:
            db.close()

    async def _do_stash(self, repo_id: Optional[int], params: dict) -> dict:
        from app.core.database import SessionLocal
        from app.modules.git_repos.services.repo_service import GitRepoService
        from app.modules.git_repos.services.git_command import GitCommandService

        db = SessionLocal()
        try:
            svc = GitRepoService()
            repo = svc.get_repo(db, repo_id)
            if not repo:
                return {"success": False, "stderr": "레포지토리를 찾을 수 없습니다."}
            git = GitCommandService()
            message = params.get("message")
            ok, stdout, stderr = await git.stash_save(repo.path, message)
            svc.log_operation(db, repo.id, "stash", "success" if ok else "failure", message, stderr or stdout)
            return {"success": ok, "stdout": stdout, "stderr": stderr}
        finally:
            db.close()

    async def _do_stash_pop(self, repo_id: Optional[int], params: dict) -> dict:
        from app.core.database import SessionLocal
        from app.modules.git_repos.services.repo_service import GitRepoService
        from app.modules.git_repos.services.git_command import GitCommandService

        db = SessionLocal()
        try:
            svc = GitRepoService()
            repo = svc.get_repo(db, repo_id)
            if not repo:
                return {"success": False, "stderr": "레포지토리를 찾을 수 없습니다."}
            git = GitCommandService()
            ok, stdout, stderr = await git.stash_pop(repo.path)
            svc.log_operation(db, repo.id, "stash_pop", "success" if ok else "failure", None, stderr or stdout)
            return {"success": ok, "stdout": stdout, "stderr": stderr}
        finally:
            db.close()

    async def _do_refresh(self, repo_id: Optional[int], params: dict) -> dict:
        from app.core.database import SessionLocal
        from app.modules.git_repos.services.repo_service import GitRepoService

        db = SessionLocal()
        try:
            svc = GitRepoService()
            repo = svc.get_repo(db, repo_id)
            if not repo:
                return {"success": False, "stderr": "레포지토리를 찾을 수 없습니다."}
            await svc.refresh_status(db, repo)
            return {"success": True, "stdout": "상태 갱신 완료"}
        finally:
            db.close()

    async def _do_refresh_all(self, repo_id: Optional[int], params: dict) -> dict:
        from app.core.database import SessionLocal
        from app.modules.git_repos.services.repo_service import GitRepoService

        db = SessionLocal()
        try:
            svc = GitRepoService()
            repos = await svc.refresh_all(db)
            return {"success": True, "stdout": f"{len(repos)}개 레포지토리 상태 갱신 완료"}
        finally:
            db.close()

    async def _do_batch_commit(self, repo_id: Optional[int], params: dict) -> dict:
        from app.core.database import SessionLocal
        from app.modules.git_repos.services.repo_service import GitRepoService

        db = SessionLocal()
        try:
            svc = GitRepoService()
            repo_ids = params.get("repo_ids", [])
            message = params.get("message", "")
            results = []
            for rid in repo_ids:
                repo = svc.get_repo(db, rid)
                if not repo:
                    results.append({"repo_id": rid, "success": False, "message": "레포지토리를 찾을 수 없습니다."})
                    continue
                result = await svc.commit_repo(db, repo, message, stage_all=True)
                results.append({"repo_id": rid, "success": result.success, "message": result.stdout or result.stderr})
            return {"success": True, "results": results}
        finally:
            db.close()

    async def _do_batch_push(self, repo_id: Optional[int], params: dict) -> dict:
        from app.core.database import SessionLocal
        from app.modules.git_repos.services.repo_service import GitRepoService

        db = SessionLocal()
        try:
            svc = GitRepoService()
            repo_ids = params.get("repo_ids", [])
            results = []
            for rid in repo_ids:
                repo = svc.get_repo(db, rid)
                if not repo:
                    results.append({"repo_id": rid, "success": False, "message": "레포지토리를 찾을 수 없습니다."})
                    continue
                result = await svc.smart_push_repo(db, repo)
                results.append({"repo_id": rid, "success": result.success, "message": result.stdout or result.stderr})
            return {"success": True, "results": results}
        finally:
            db.close()

    async def _do_generate_message(self, repo_id: Optional[int], params: dict) -> dict:
        """generate-message는 LLM 큐를 사용하는 기존 방식 유지 — 워커에서는 처리하지 않음."""
        return {"success": False, "stderr": "generate-message는 routes에서 직접 처리됩니다."}
