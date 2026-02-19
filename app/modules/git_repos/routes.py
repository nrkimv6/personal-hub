"""Git Repository 관리 API 라우트."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional

from app.core.database import get_db
from app.modules.git_repos import schemas
from app.modules.git_repos.services.repo_service import GitRepoService

router = APIRouter(prefix="/api/v1/git-repos", tags=["git-repos"])


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
# 상태 조회 엔드포인트
# ───────────────────────────────────────────

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


@router.post("/{repo_id}/refresh", response_model=schemas.RepoResponse)
async def refresh_status(repo_id: int, db: Session = Depends(get_db)):
    """단일 레포지토리 상태 갱신."""
    svc = GitRepoService()
    repo = svc.get_repo(db, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="레포지토리를 찾을 수 없습니다.")
    return await svc.refresh_status(db, repo)


@router.post("/refresh-all", response_model=List[schemas.RepoResponse])
async def refresh_all(db: Session = Depends(get_db)):
    """전체 레포지토리 상태 갱신."""
    svc = GitRepoService()
    return await svc.refresh_all(db)


# ───────────────────────────────────────────
# 작업 실행 엔드포인트
# ───────────────────────────────────────────

@router.post("/{repo_id}/stage", response_model=schemas.OperationResult)
async def stage_files(repo_id: int, body: schemas.StageRequest, db: Session = Depends(get_db)):
    """파일 스테이징."""
    from app.modules.git_repos.services.git_command import GitCommandService
    svc = GitRepoService()
    repo = svc.get_repo(db, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="레포지토리를 찾을 수 없습니다.")
    git = GitCommandService()
    ok, stdout, stderr = await git.stage_files(repo.path, body.files)
    return schemas.OperationResult(success=ok, stdout=stdout, stderr=stderr)


@router.post("/{repo_id}/unstage", response_model=schemas.OperationResult)
async def unstage_files(repo_id: int, body: schemas.StageRequest, db: Session = Depends(get_db)):
    """파일 언스테이징."""
    from app.modules.git_repos.services.git_command import GitCommandService
    svc = GitRepoService()
    repo = svc.get_repo(db, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="레포지토리를 찾을 수 없습니다.")
    git = GitCommandService()
    ok, stdout, stderr = await git.unstage_files(repo.path, body.files)
    return schemas.OperationResult(success=ok, stdout=stdout, stderr=stderr)


@router.post("/{repo_id}/commit", response_model=schemas.OperationResult)
async def commit(repo_id: int, body: schemas.CommitRequest, db: Session = Depends(get_db)):
    """커밋 실행."""
    svc = GitRepoService()
    repo = svc.get_repo(db, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="레포지토리를 찾을 수 없습니다.")
    result = await svc.commit_repo(db, repo, body.message, body.stage_all)
    return result


@router.post("/{repo_id}/push", response_model=schemas.OperationResult)
async def push(repo_id: int, db: Session = Depends(get_db)):
    """푸시 실행."""
    svc = GitRepoService()
    repo = svc.get_repo(db, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="레포지토리를 찾을 수 없습니다.")
    result = await svc.push_repo(db, repo)
    return result


@router.post("/{repo_id}/pull", response_model=schemas.OperationResult)
async def pull(repo_id: int, db: Session = Depends(get_db)):
    """풀 실행."""
    svc = GitRepoService()
    repo = svc.get_repo(db, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="레포지토리를 찾을 수 없습니다.")
    result = await svc.pull_repo(db, repo)
    return result


@router.post("/{repo_id}/fetch", response_model=schemas.OperationResult)
async def fetch(repo_id: int, db: Session = Depends(get_db)):
    """페치 실행."""
    svc = GitRepoService()
    repo = svc.get_repo(db, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="레포지토리를 찾을 수 없습니다.")
    result = await svc.fetch_repo(db, repo)
    return result


@router.post("/{repo_id}/stash", response_model=schemas.OperationResult)
async def stash_save(repo_id: int, body: schemas.StashRequest, db: Session = Depends(get_db)):
    """스태시 저장."""
    from app.modules.git_repos.services.git_command import GitCommandService
    svc = GitRepoService()
    repo = svc.get_repo(db, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="레포지토리를 찾을 수 없습니다.")
    git = GitCommandService()
    ok, stdout, stderr = await git.stash_save(repo.path, body.message)
    svc.log_operation(db, repo.id, "stash", "success" if ok else "failure", body.message, stderr or stdout)
    return schemas.OperationResult(success=ok, stdout=stdout, stderr=stderr)


@router.post("/{repo_id}/stash-pop", response_model=schemas.OperationResult)
async def stash_pop(repo_id: int, db: Session = Depends(get_db)):
    """스태시 복원."""
    from app.modules.git_repos.services.git_command import GitCommandService
    svc = GitRepoService()
    repo = svc.get_repo(db, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="레포지토리를 찾을 수 없습니다.")
    git = GitCommandService()
    ok, stdout, stderr = await git.stash_pop(repo.path)
    svc.log_operation(db, repo.id, "stash_pop", "success" if ok else "failure", None, stderr or stdout)
    return schemas.OperationResult(success=ok, stdout=stdout, stderr=stderr)


# ───────────────────────────────────────────
# 일괄 작업 + LLM 메시지 생성
# ───────────────────────────────────────────

@router.post("/batch-commit")
async def batch_commit(body: schemas.BatchCommitRequest, db: Session = Depends(get_db)):
    """여러 레포 일괄 커밋."""
    svc = GitRepoService()
    results = []
    for repo_id in body.repo_ids:
        repo = svc.get_repo(db, repo_id)
        if not repo:
            results.append(schemas.BatchResult(repo_id=repo_id, success=False, message="레포지토리를 찾을 수 없습니다."))
            continue
        result = await svc.commit_repo(db, repo, body.message, stage_all=True)
        results.append(schemas.BatchResult(repo_id=repo_id, success=result.success, message=result.stdout or result.stderr))
    return {"results": results}


@router.post("/batch-push")
async def batch_push(body: schemas.BatchPushRequest, db: Session = Depends(get_db)):
    """여러 레포 일괄 푸시."""
    svc = GitRepoService()
    results = []
    for repo_id in body.repo_ids:
        repo = svc.get_repo(db, repo_id)
        if not repo:
            results.append(schemas.BatchResult(repo_id=repo_id, success=False, message="레포지토리를 찾을 수 없습니다."))
            continue
        result = await svc.push_repo(db, repo)
        results.append(schemas.BatchResult(repo_id=repo_id, success=result.success, message=result.stdout or result.stderr))
    return {"results": results}


@router.post("/{repo_id}/generate-message")
async def generate_commit_message(repo_id: int, db: Session = Depends(get_db)):
    """diff를 LLM에 전달해 커밋 메시지 자동 생성."""
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
        import json

        prompt = f"""아래 git diff를 분석하고 Conventional Commits 형식의 한국어 커밋 메시지를 1줄로 작성하세요.

형식: <type>: <설명>
type: feat | fix | refactor | docs | chore | test

diff:
{diff[:3000]}

커밋 메시지만 출력하세요."""

        llm_svc = LLMService(db)
        req = llm_svc.create_request(
            request_type="commit_message",
            prompt=prompt,
            model="claude-haiku-4-5",
            max_tokens=100,
        )
        db.commit()

        # 동기 처리 시도 (빠른 응답)
        import asyncio
        for _ in range(30):
            await asyncio.sleep(1)
            db.refresh(req)
            if req.status in ("completed", "failed"):
                break

        if req.status == "completed" and req.response:
            resp = json.loads(req.response)
            msg = resp.get("content", [{}])[0].get("text", "").strip()
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
