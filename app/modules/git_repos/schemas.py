"""Git Repository Pydantic 스키마."""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, validator

from app.modules.claude_worker.services import provider_registry


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


class GenerateMessageRequest(BaseModel):
    provider: str = "claude"
    model: str = ""

    @validator("provider")
    def validate_provider(cls, v):
        if not provider_registry.is_supported(v):
            raise ValueError(f"지원되지 않는 provider: {v}")
        return v


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


# ───────────────────────────────────────────
# 비동기 작업 응답 스키마
# ───────────────────────────────────────────

class GitTaskResponse(BaseModel):
    task_id: str
    status: str = "pending"


class GitTaskResult(BaseModel):
    task_id: str
    status: str
    result: Optional[OperationResult] = None
    completed_at: Optional[str] = None


# ───────────────────────────────────────────
# Auto Cleanup 스키마
# ───────────────────────────────────────────

class AutoCleanupRequest(BaseModel):
    patterns: List[str] = ["tmp_*"]
    provider: str = "claude"

    @validator("provider")
    def validate_provider(cls, v):
        if not provider_registry.is_supported(v):
            raise ValueError(f"지원되지 않는 provider: {v}")
        return v


class AutoCleanupTaskResponse(BaseModel):
    request_id: int
    status: str = "pending"


class AutoCleanupResult(BaseModel):
    success: bool
    moved: List[str] = []
    commits: List[dict] = []
    error: str = ""
