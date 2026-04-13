"""Git Repository 관리 API 라우트."""
import json
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional

from app.core.database import get_db
from app.modules.git_repos import schemas
from app.modules.git_repos.schemas import GitTaskResponse
from app.modules.git_repos.services.repo_service import GitRepoService
from app.shared.redis.client import RedisClient
from app.shared.redis.queue import RedisQueue, GIT_REPOS_TASK_QUEUE

router = APIRouter(prefix="/api/v1/git-repos", tags=["git-repos"])


# ───────────────────────────────────────────
# 내부 헬퍼
# ───────────────────────────────────────────

async def _enqueue_task(action: str, repo_id: Optional[int], params: dict) -> GitTaskResponse:
    """Redis 큐에 git 작업 발행 후 task_id 반환.

    Args:
        action: 수행할 작업 이름
        repo_id: 대상 레포지토리 ID (없으면 None)
        params: 작업별 추가 파라미터

    Returns:
        GitTaskResponse: task_id와 status="pending"

    Raises:
        HTTPException(503): Redis 미연결 시
    """
    client = await RedisClient.get_client()
    if client is None:
        raise HTTPException(status_code=503, detail="워커 서비스 미사용 (Redis 미연결)")

    task_id = str(uuid4())
    queue = RedisQueue(client, GIT_REPOS_TASK_QUEUE)
    await queue.push({
        "task_id": task_id,
        "action": action,
        "repo_id": repo_id,
        "params": params,
        "requested_at": datetime.now().isoformat(),
    })
    return GitTaskResponse(task_id=task_id, status="pending")


# ───────────────────────────────────────────
# CRUD 엔드포인트
# ───────────────────────────────────────────

@router.get("", response_model=List[schemas.RepoResponse])
async def list_repos(db: Session = Depends(get_db)):
    """등록된 모든 레포지토리 목록 조회."""
    svc = GitRepoService()
    return svc.list_repos(db)


@router.post("", response_model=schemas.RepoResponse)
async def create_repo(body: schemas.RepoCreate, db: Session = Depends(get_db)):
    """레포지토리 등록."""
    svc = GitRepoService()
    try:
        return await svc.create_repo(db, body.path, body.alias)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/{repo_id}", response_model=schemas.RepoResponse)
async def update_repo(repo_id: int, body: schemas.RepoUpdate, db: Session = Depends(get_db)):
    """레포지토리 정보 수정."""
    svc = GitRepoService()
    repo = svc.update_repo(db, repo_id, body.alias, body.is_active, body.sort_order)
    if not repo:
        raise HTTPException(status_code=404, detail="레포지토리를 찾을 수 없습니다.")
    return repo


@router.delete("/{repo_id}")
async def delete_repo(repo_id: int, db: Session = Depends(get_db)):
    """레포지토리 등록 해제."""
    svc = GitRepoService()
    if not svc.delete_repo(db, repo_id):
        raise HTTPException(status_code=404, detail="레포지토리를 찾을 수 없습니다.")
    return {"success": True}


@router.get("/discover")
async def discover_repos(base_path: str = Query(..., description="탐색할 기본 디렉토리 경로")):
    """base_path 하위 1단계에서 .git 포함 폴더 목록 반환."""
    svc = GitRepoService()
    try:
        paths = await svc.discover_repos(base_path)
        return {"paths": paths, "count": len(paths)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ───────────────────────────────────────────
# 비동기 작업 결과 폴링
# ───────────────────────────────────────────

@router.get("/tasks/{task_id}", response_model=schemas.GitTaskResult)
async def get_task_result(task_id: str):
    """비동기 작업 결과 폴링.

    Redis에서 git_repos:result:{task_id} 키를 조회합니다.
    아직 처리 중이면 status="pending"을 반환합니다.
    """
    client = await RedisClient.get_client()
    if client is None:
        return schemas.GitTaskResult(task_id=task_id, status="pending")

    key = f"git_repos:result:{task_id}"
    try:
        data = await client.get(key)
        if data is None:
            return schemas.GitTaskResult(task_id=task_id, status="pending")
        parsed = json.loads(data)
        result_dict = parsed.get("result")
        result_obj = schemas.OperationResult(**result_dict) if result_dict and isinstance(result_dict, dict) and "success" in result_dict else None
        return schemas.GitTaskResult(
            task_id=parsed.get("task_id", task_id),
            status=parsed.get("status", "completed"),
            result=result_obj,
            completed_at=parsed.get("completed_at"),
        )
    except Exception:
        return schemas.GitTaskResult(task_id=task_id, status="pending")


# ───────────────────────────────────────────
# 상태 조회 엔드포인트
# ───────────────────────────────────────────

@router.get("/{repo_id}", response_model=schemas.RepoResponse)
async def get_repo(repo_id: int, db: Session = Depends(get_db)):
    """레포지토리 단건 조회."""
    svc = GitRepoService()
    repo = svc.get_repo(db, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="레포지토리를 찾을 수 없습니다.")
    return repo


@router.get("/{repo_id}/status", response_model=schemas.RepoStatus)
async def get_status(repo_id: int, db: Session = Depends(get_db)):
    """레포지토리 상세 상태 조회 (파일 목록, branch, ahead/behind)."""
    svc = GitRepoService()
    repo = svc.get_repo(db, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="레포지토리를 찾을 수 없습니다.")
    try:
        return await svc.get_detailed_status(repo.path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{repo_id}/diff")
async def get_diff(repo_id: int, staged: bool = False, db: Session = Depends(get_db)):
    """diff 전문 반환."""
    from app.modules.git_repos.services.git_command import GitCommandService
    svc = GitRepoService()
    repo = svc.get_repo(db, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="레포지토리를 찾을 수 없습니다.")
    git = GitCommandService()
    diff = await git.get_diff(repo.path, staged=staged)
    return {"diff": diff}


@router.get("/{repo_id}/log", response_model=List[schemas.LogEntry])
async def get_log(repo_id: int, n: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    """최근 커밋 로그 조회."""
    from app.modules.git_repos.services.git_command import GitCommandService
    svc = GitRepoService()
    repo = svc.get_repo(db, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="레포지토리를 찾을 수 없습니다.")
    git = GitCommandService()
    return await git.get_log(repo.path, n=n)


@router.post("/{repo_id}/refresh", response_model=schemas.GitTaskResponse)
async def refresh_status(repo_id: int, db: Session = Depends(get_db)):
    """단일 레포지토리 상태 갱신 (큐 발행)."""
    svc = GitRepoService()
    repo = svc.get_repo(db, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="레포지토리를 찾을 수 없습니다.")
    return await _enqueue_task("refresh", repo_id, {})


@router.post("/refresh-all", response_model=schemas.GitTaskResponse)
async def refresh_all(db: Session = Depends(get_db)):
    """전체 레포지토리 상태 갱신 (큐 발행)."""
    return await _enqueue_task("refresh-all", None, {})


# ───────────────────────────────────────────
# 작업 실행 엔드포인트 (큐 발행)
# ───────────────────────────────────────────

@router.post("/{repo_id}/stage", response_model=schemas.GitTaskResponse)
async def stage_files(repo_id: int, body: schemas.StageRequest, db: Session = Depends(get_db)):
    """파일 스테이징 (큐 발행)."""
    svc = GitRepoService()
    repo = svc.get_repo(db, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="레포지토리를 찾을 수 없습니다.")
    return await _enqueue_task("stage", repo_id, {"files": body.files})


@router.post("/{repo_id}/unstage", response_model=schemas.GitTaskResponse)
async def unstage_files(repo_id: int, body: schemas.StageRequest, db: Session = Depends(get_db)):
    """파일 언스테이징 (큐 발행)."""
    svc = GitRepoService()
    repo = svc.get_repo(db, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="레포지토리를 찾을 수 없습니다.")
    return await _enqueue_task("unstage", repo_id, {"files": body.files})


@router.post("/{repo_id}/commit", response_model=schemas.GitTaskResponse)
async def commit(repo_id: int, body: schemas.CommitRequest, db: Session = Depends(get_db)):
    """커밋 실행 (큐 발행)."""
    svc = GitRepoService()
    repo = svc.get_repo(db, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="레포지토리를 찾을 수 없습니다.")
    return await _enqueue_task("commit", repo_id, {"message": body.message, "stage_all": body.stage_all})


@router.post("/{repo_id}/push", response_model=schemas.GitTaskResponse)
async def push(repo_id: int, db: Session = Depends(get_db)):
    """푸시 실행 (큐 발행)."""
    svc = GitRepoService()
    repo = svc.get_repo(db, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="레포지토리를 찾을 수 없습니다.")
    return await _enqueue_task("push", repo_id, {})


@router.post("/{repo_id}/pull", response_model=schemas.GitTaskResponse)
async def pull(repo_id: int, db: Session = Depends(get_db)):
    """풀 실행 (큐 발행)."""
    svc = GitRepoService()
    repo = svc.get_repo(db, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="레포지토리를 찾을 수 없습니다.")
    return await _enqueue_task("pull", repo_id, {})


@router.post("/{repo_id}/fetch", response_model=schemas.GitTaskResponse)
async def fetch(repo_id: int, db: Session = Depends(get_db)):
    """페치 실행 (큐 발행)."""
    svc = GitRepoService()
    repo = svc.get_repo(db, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="레포지토리를 찾을 수 없습니다.")
    return await _enqueue_task("fetch", repo_id, {})


@router.post("/{repo_id}/stash", response_model=schemas.GitTaskResponse)
async def stash_save(repo_id: int, body: schemas.StashRequest, db: Session = Depends(get_db)):
    """스태시 저장 (큐 발행)."""
    svc = GitRepoService()
    repo = svc.get_repo(db, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="레포지토리를 찾을 수 없습니다.")
    return await _enqueue_task("stash", repo_id, {"message": body.message})


@router.post("/{repo_id}/stash-pop", response_model=schemas.GitTaskResponse)
async def stash_pop(repo_id: int, db: Session = Depends(get_db)):
    """스태시 복원 (큐 발행)."""
    svc = GitRepoService()
    repo = svc.get_repo(db, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="레포지토리를 찾을 수 없습니다.")
    return await _enqueue_task("stash-pop", repo_id, {})


# ───────────────────────────────────────────
# 일괄 작업 + LLM 메시지 생성
# ───────────────────────────────────────────

@router.post("/batch-commit", response_model=schemas.GitTaskResponse)
async def batch_commit(body: schemas.BatchCommitRequest, db: Session = Depends(get_db)):
    """여러 레포 일괄 커밋 (큐 발행)."""
    return await _enqueue_task("batch-commit", None, {"repo_ids": body.repo_ids, "message": body.message})


@router.post("/batch-push", response_model=schemas.GitTaskResponse)
async def batch_push(body: schemas.BatchPushRequest, db: Session = Depends(get_db)):
    """여러 레포 일괄 푸시 (큐 발행)."""
    return await _enqueue_task("batch-push", None, {"repo_ids": body.repo_ids})


@router.post("/{repo_id}/generate-message")
async def generate_commit_message(
    repo_id: int,
    body: schemas.GenerateMessageRequest = Body(default_factory=schemas.GenerateMessageRequest),
    db: Session = Depends(get_db),
):
    """diff를 LLM에 전달해 커밋 메시지 자동 생성.

    diff 조회는 route에서 직접 수행하고,
    LLM 요청/폴링은 기존 코드(LLM 큐) 방식 유지.
    """
    from app.modules.git_repos.services.git_command import GitCommandService
    svc = GitRepoService()
    repo = svc.get_repo(db, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="레포지토리를 찾을 수 없습니다.")

    git = GitCommandService()
    diff = await git.get_diff(repo.path, staged=True)
    if not diff.strip():
        diff = await git.get_diff(repo.path, staged=False)
    if not diff.strip():
        raise HTTPException(status_code=400, detail="변경 사항이 없습니다.")

    try:
        from app.modules.claude_worker.services.llm_service import LLMService
        from app.modules.claude_worker.models import LLMRequest
        import asyncio as _asyncio

        prompt = f"""아래 git diff를 분석하고 Conventional Commits 형식의 한국어 커밋 메시지를 1줄로 작성하세요.

형식: <type>: <설명>
type: feat | fix | refactor | docs | chore | test

diff:
{diff[:3000]}

커밋 메시지만 출력하세요."""

        # model 기본값 해석 — registry 기반
        from app.modules.claude_worker.services import provider_registry as _pr
        _provider_meta = _pr.get_provider(body.provider)
        _default_model = _provider_meta.default_model if _provider_meta else ""
        resolved_model = body.model if body.model else _default_model

        llm_svc = LLMService(db)
        req = llm_svc.enqueue(
            caller_type="git_repos",
            caller_id=f"generate-message-{repo_id}",
            prompt=prompt,
            requested_by="api",
            request_source="git_commit_message",
            provider=body.provider,
            model=resolved_model,
            cli_options={"parse_json": False},
            queue_name="utility",
        )
        db.commit()

        # 동기 처리 시도 (빠른 응답)
        for _ in range(30):
            await _asyncio.sleep(1)
            db.refresh(req)
            if req.status in ("completed", "failed"):
                break

        if req.status == "completed" and req.raw_response:
            msg = req.raw_response.strip()
            return {"message": msg, "request_id": req.id}
        else:
            return {"message": "", "request_id": req.id, "status": req.status}

    except ImportError:
        raise HTTPException(status_code=503, detail="LLM 서비스를 사용할 수 없습니다.")


@router.get("/{repo_id}/operations", response_model=List[schemas.OperationLogResponse])
async def get_operations(
    repo_id: int,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db)
):
    """작업 이력 로그 조회."""
    from app.modules.git_repos.models import GitOperationLog
    svc = GitRepoService()
    repo = svc.get_repo(db, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="레포지토리를 찾을 수 없습니다.")
    logs = (
        db.query(GitOperationLog)
        .filter(GitOperationLog.repo_id == repo_id)
        .order_by(GitOperationLog.created_at.desc())
        .limit(limit)
        .all()
    )
    return logs
