"""Claude 세션 API 라우터."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.claude_sessions.session_parser import SessionParser, encode_project_path

logger = logging.getLogger("claude_sessions.session_routes")

router = APIRouter(prefix="/api/v1/claude-sessions", tags=["Claude Sessions"])

_parser = SessionParser()

CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"


# ── 응답 스키마 ─────────────────────────────────────────────────────────────


class ProjectInfo(BaseModel):
    encoded: str
    decoded: Optional[str] = None


class SessionMetaResponse(BaseModel):
    id: str
    mtime: str
    line_count: int
    source_type: str
    agent_name: Optional[str] = None
    cwd: Optional[str] = None
    git_branch: Optional[str] = None
    first_message: Optional[str] = None


class SummarizeResponse(BaseModel):
    request_id: int
    status: str


class SummarizeRecentResponse(BaseModel):
    request_ids: List[int]
    count: int


class SummaryResult(BaseModel):
    session_id: str
    status: str
    summary: Optional[str] = None


# ── 엔드포인트 ───────────────────────────────────────────────────────────────


@router.get("/projects", response_model=List[ProjectInfo])
def list_projects():
    """~/.claude/projects/ 내 디렉토리 목록."""
    if not CLAUDE_PROJECTS_DIR.exists():
        return []
    result: list[ProjectInfo] = []
    for d in sorted(CLAUDE_PROJECTS_DIR.iterdir()):
        if d.is_dir():
            result.append(ProjectInfo(encoded=d.name))
    return result


@router.get("/{encoded_project}/sessions", response_model=List[SessionMetaResponse])
def list_sessions(
    encoded_project: str,
    limit: int = Query(20, ge=1, le=200),
    since: Optional[str] = Query(None, description="ISO8601 datetime"),
    source_type: Optional[str] = Query(None),
):
    """세션 목록 조회."""
    sessions_dir = CLAUDE_PROJECTS_DIR / encoded_project
    if not sessions_dir.exists():
        raise HTTPException(status_code=404, detail="프로젝트 세션 디렉토리를 찾을 수 없습니다")

    # encoded → 프로젝트 경로 역추적은 어렵지만, 파서가 encoded 디렉토리를 직접 받도록 우회
    since_dt: Optional[datetime] = None
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
        except ValueError:
            raise HTTPException(status_code=400, detail="since 형식 오류 (ISO8601 필요)")

    # encoded 디렉토리 직접 사용 — list_sessions를 bypass해 직접 파싱
    from app.modules.claude_sessions.session_parser import SessionMeta
    results: list[SessionMetaResponse] = []
    all_files = sorted(sessions_dir.glob("*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)

    for jsonl_file in all_files:
        try:
            stat = jsonl_file.stat()
            mtime = datetime.fromtimestamp(stat.st_mtime)
            if since_dt and mtime < since_dt:
                continue

            first_line_obj: dict = {}
            line_count = 0
            cwd: Optional[str] = None
            git_branch: Optional[str] = None
            first_message: Optional[str] = None

            import json
            with open(jsonl_file, encoding="utf-8", errors="replace") as f:
                for i, raw_line in enumerate(f):
                    line_count += 1
                    raw_line = raw_line.strip()
                    if not raw_line:
                        continue
                    try:
                        obj = json.loads(raw_line)
                    except json.JSONDecodeError:
                        continue
                    if i == 0:
                        first_line_obj = obj
                    if obj.get("type") in ("user", "assistant") and cwd is None:
                        cwd = obj.get("cwd")
                        git_branch = obj.get("gitBranch")
                        content = _parser.extract_content(obj)
                        if content:
                            first_message = content[:100]

            src_type, agent_name = _parser.classify_source(first_line_obj)
            if source_type and src_type != source_type:
                continue

            results.append(SessionMetaResponse(
                id=jsonl_file.stem,
                mtime=mtime.isoformat(),
                line_count=line_count,
                source_type=src_type,
                agent_name=agent_name,
                cwd=cwd,
                git_branch=git_branch,
                first_message=first_message,
            ))

            if len(results) >= limit:
                break
        except OSError as e:
            logger.warning(f"세션 파일 읽기 실패: {jsonl_file} — {e}")

    return results


@router.post("/{encoded_project}/sessions/{session_id}/summarize", response_model=SummarizeResponse)
def summarize_session(
    encoded_project: str,
    session_id: str,
    db: Session = Depends(get_db),
):
    """단일 세션 요약 enqueue."""
    sessions_dir = CLAUDE_PROJECTS_DIR / encoded_project
    jsonl_path = sessions_dir / f"{session_id}.jsonl"
    if not jsonl_path.exists():
        raise HTTPException(status_code=404, detail="세션 파일을 찾을 수 없습니다")

    from app.modules.claude_sessions.session_summarizer import SessionSummarizer
    from app.modules.claude_sessions.session_parser import SessionMeta

    # project_path → encoded 디렉토리를 직접 path로 사용하는 대신 임시 meta 생성
    summarizer = SessionSummarizer(db)

    import json as _json
    stat = jsonl_path.stat()
    mtime = datetime.fromtimestamp(stat.st_mtime)
    first_line_obj: dict = {}
    line_count = 0
    cwd = None
    git_branch = None
    first_message = None
    with open(jsonl_path, encoding="utf-8", errors="replace") as f:
        for i, raw_line in enumerate(f):
            line_count += 1
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                obj = _json.loads(raw_line)
            except _json.JSONDecodeError:
                continue
            if i == 0:
                first_line_obj = obj
            if obj.get("type") in ("user", "assistant") and cwd is None:
                cwd = obj.get("cwd")
                git_branch = obj.get("gitBranch")
                content = _parser.extract_content(obj)
                if content:
                    first_message = content[:100]

    src_type, agent_name = _parser.classify_source(first_line_obj)
    meta = SessionMeta(
        id=session_id,
        path=jsonl_path,
        mtime=mtime,
        line_count=line_count,
        source_type=src_type,
        agent_name=agent_name,
        cwd=cwd,
        git_branch=git_branch,
        first_message=first_message,
    )
    messages = _parser.extract_messages(jsonl_path)
    prompt = _parser.build_summary_prompt(messages, meta)

    from app.modules.claude_sessions.session_summarizer import CALLER_TYPE, MODEL, QUEUE_NAME
    from app.modules.claude_worker.services.llm_service import LLMService
    llm = LLMService(db)
    req = llm.enqueue(
        caller_type=CALLER_TYPE,
        caller_id=session_id,
        prompt=prompt,
        requested_by="api",
        model=MODEL,
        queue_name=QUEUE_NAME,
    )
    return SummarizeResponse(request_id=req.id, status=req.status)


@router.get("/summary/{session_id}", response_model=SummaryResult)
def get_summary(session_id: str, db: Session = Depends(get_db)):
    """요약 결과 조회."""
    from app.modules.claude_sessions.session_summarizer import SessionSummarizer
    summarizer = SessionSummarizer(db)
    req = summarizer.get_summary_result(session_id)
    if req is None:
        return SummaryResult(session_id=session_id, status="not_found")
    summary_text: Optional[str] = None
    if req.status == "completed":
        summary_text = req.result
    return SummaryResult(session_id=session_id, status=req.status, summary=summary_text)


@router.post("/{encoded_project}/summarize-recent", response_model=SummarizeRecentResponse)
def summarize_recent(
    encoded_project: str,
    limit: int = Query(8, ge=1, le=50),
    since: Optional[str] = Query(None),
    source_type: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """최근 N개 세션 일괄 enqueue."""
    sessions_dir = CLAUDE_PROJECTS_DIR / encoded_project
    if not sessions_dir.exists():
        raise HTTPException(status_code=404, detail="프로젝트 세션 디렉토리를 찾을 수 없습니다")

    since_dt: Optional[datetime] = None
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
        except ValueError:
            raise HTTPException(status_code=400, detail="since 형식 오류")

    # 세션 목록 조회
    import json as _json
    all_files = sorted(sessions_dir.glob("*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)
    session_ids: list[str] = []

    for jsonl_file in all_files:
        if len(session_ids) >= limit:
            break
        try:
            mtime = datetime.fromtimestamp(jsonl_file.stat().st_mtime)
            if since_dt and mtime < since_dt:
                continue

            if source_type:
                with open(jsonl_file, encoding="utf-8", errors="replace") as f:
                    first_line = f.readline().strip()
                if first_line:
                    try:
                        first_obj = _json.loads(first_line)
                        src, _ = _parser.classify_source(first_obj)
                        if src != source_type:
                            continue
                    except _json.JSONDecodeError:
                        continue

            session_ids.append(jsonl_file.stem)
        except OSError:
            continue

    from app.modules.claude_sessions.session_summarizer import SessionSummarizer, CALLER_TYPE, MODEL, QUEUE_NAME
    from app.modules.claude_worker.services.llm_service import LLMService

    llm = LLMService(db)
    request_ids: list[int] = []
    for sid in session_ids:
        jsonl_path = sessions_dir / f"{sid}.jsonl"
        try:
            req = llm.enqueue(
                caller_type=CALLER_TYPE,
                caller_id=sid,
                prompt=f"[batch] {sid}",
                requested_by="api",
                model=MODEL,
                queue_name=QUEUE_NAME,
            )
            request_ids.append(req.id)
        except Exception as e:
            logger.warning(f"일괄 요약 enqueue 실패: {sid} — {e}")

    return SummarizeRecentResponse(request_ids=request_ids, count=len(request_ids))
