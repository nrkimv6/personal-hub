"""Git Repository Pydantic 스키마."""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel


# ───────────────────────────────────────────
# GitRepo 스키마
# ───────────────────────────────────────────

class RepoCreate(BaseModel):
    path: str
    alias: Optional[str] = None


class RepoUpdate(BaseModel):
    alias: Optional[str] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None


class RepoStatus(BaseModel):
    """git status 결과 (상세)."""
    branch: str
    upstream: Optional[str] = None
    ahead: int = 0
    behind: int = 0
    status: str                         # "clean" | "dirty" | "conflict"
    staged: List[str] = []
    unstaged: List[str] = []
    untracked: List[str] = []


class RepoResponse(BaseModel):
    id: int
    path: str
    alias: Optional[str] = None
    is_active: bool
    sort_order: int
    last_status: Optional[str] = None
    last_branch: Optional[str] = None
    last_ahead: Optional[int] = None
    last_behind: Optional[int] = None
    last_checked_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ───────────────────────────────────────────
# GitOperationLog 스키마
# ───────────────────────────────────────────

class OperationLogResponse(BaseModel):
    id: int
    repo_id: int
    operation: str
    status: str
    message: Optional[str] = None
    detail: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ───────────────────────────────────────────
# Git Log Entry
# ───────────────────────────────────────────

class LogEntry(BaseModel):
    hash: str
    short_hash: str
    message: str
    author: str
    date: str


# ───────────────────────────────────────────
# 요청 바디 스키마
# ───────────────────────────────────────────

class StageRequest(BaseModel):
    files: List[str]


class CommitRequest(BaseModel):
    message: str
    stage_all: bool = False


class StashRequest(BaseModel):
    message: Optional[str] = None


class BatchCommitRequest(BaseModel):
    repo_ids: List[int]
    message: str


class BatchPushRequest(BaseModel):
    repo_ids: List[int]


# ───────────────────────────────────────────
# 응답 래퍼
# ───────────────────────────────────────────

class OperationResult(BaseModel):
    success: bool
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    message: Optional[str] = None


class BatchResult(BaseModel):
    repo_id: int
    success: bool
    message: Optional[str] = None
