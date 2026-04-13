"""Claude 세션 JSONL 파서.

~/.claude/projects/{encoded_path}/*.jsonl 파일을 파싱하여
세션 메타데이터 및 메시지를 추출합니다.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional

logger = logging.getLogger("claude_sessions.session_parser")

SourceType = Literal["user", "agent", "llm-worker", "unknown"]


@dataclass
class SessionMeta:
    id: str
    path: Path
    mtime: datetime
    line_count: int
    source_type: SourceType
    agent_name: Optional[str] = None
    cwd: Optional[str] = None
    git_branch: Optional[str] = None
    first_message: Optional[str] = None


def encode_project_path(abs_path: str) -> str:
    """절대 경로를 ~/.claude/projects/ 인코딩 형식으로 변환.

    D:\\work\\foo → D--work-foo
    /d/work/foo  → d--work-foo
    """
    path = abs_path
    # 콜론 제거 (Windows 드라이브 구분자)
    path = path.replace(":", "")
    # 역슬래시와 슬래시를 -- 로 치환
    path = path.replace("\\", "--").replace("/", "--")
    # 앞뒤 -- 정리
    path = path.strip("-")
    return path


class SessionParser:
    """~/.claude/projects/ JSONL 세션 파서."""

    def get_sessions_dir(self, project_path: str) -> Path:
        """프로젝트 경로에 해당하는 Claude 세션 디렉토리 반환."""
        encoded = encode_project_path(project_path)
        return Path.home() / ".claude" / "projects" / encoded

    def classify_source(self, first_line: dict) -> tuple[SourceType, Optional[str]]:
        """첫 줄 dict를 보고 (source_type, agent_name) 반환."""
        line_type = first_line.get("type", "")
        if line_type == "permission-mode":
            return ("user", None)
        if line_type == "agent-setting":
            agent_name = first_line.get("agentSetting")
            return ("agent", agent_name)
        if line_type == "queue-operation":
            return ("llm-worker", None)
        return ("unknown", None)

    def list_sessions(
        self,
        project_path: str,
        limit: int = 20,
        since: Optional[datetime] = None,
        source_type: Optional[str] = None,
    ) -> list[SessionMeta]:
        """세션 목록 반환 (mtime 내림차순)."""
        sessions_dir = self.get_sessions_dir(project_path)
        if not sessions_dir.exists():
            return []

        results: list[SessionMeta] = []
        for jsonl_file in sessions_dir.glob("*.jsonl"):
            try:
                stat = jsonl_file.stat()
                mtime = datetime.fromtimestamp(stat.st_mtime)

                if since and mtime < since:
                    continue

                first_line_obj: dict = {}
                line_count = 0
                cwd: Optional[str] = None
                git_branch: Optional[str] = None
                first_message: Optional[str] = None

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

                        # cwd/gitBranch는 첫 user/assistant 메시지에서 추출
                        if obj.get("type") in ("user", "assistant") and cwd is None:
                            cwd = obj.get("cwd")
                            git_branch = obj.get("gitBranch")
                            if first_message is None:
                                content = self.extract_content(obj)
                                if content:
                                    first_message = content[:100]

                src_type, agent_name = self.classify_source(first_line_obj)

                if source_type and src_type != source_type:
                    continue

                results.append(
                    SessionMeta(
                        id=jsonl_file.stem,
                        path=jsonl_file,
                        mtime=mtime,
                        line_count=line_count,
                        source_type=src_type,
                        agent_name=agent_name,
                        cwd=cwd,
                        git_branch=git_branch,
                        first_message=first_message,
                    )
                )
            except OSError as e:
                logger.warning(f"세션 파일 읽기 실패: {jsonl_file} — {e}")

        results.sort(key=lambda s: s.mtime, reverse=True)
        return results[:limit]

    def extract_messages(self, jsonl_path: Path, sample: bool = True) -> list[dict]:
        """JSONL에서 user/assistant 메시지 줄만 파싱.

        sample=True이면 앞 20줄 + 중간 10줄 + 마지막 20줄 샘플링.
        """
        lines: list[dict] = []
        try:
            with open(jsonl_path, encoding="utf-8", errors="replace") as f:
                for raw_line in f:
                    raw_line = raw_line.strip()
                    if not raw_line:
                        continue
                    try:
                        obj = json.loads(raw_line)
                    except json.JSONDecodeError:
                        continue
                    if obj.get("type") in ("user", "assistant"):
                        lines.append(obj)
        except OSError as e:
            logger.warning(f"메시지 추출 실패: {jsonl_path} — {e}")
            return []

        if not sample or len(lines) <= 50:
            return lines

        # 앞 20 + 중간 10 + 마지막 20
        head = lines[:20]
        mid_start = (len(lines) - 10) // 2
        mid = lines[mid_start: mid_start + 10]
        tail = lines[-20:]
        # 중복 제거 (순서 유지)
        seen: set[int] = set()
        result: list[dict] = []
        for grp in (head, mid, tail):
            for item in grp:
                item_id = id(item)
                if item_id not in seen:
                    seen.add(item_id)
                    result.append(item)
        return result

    def extract_content(self, message_obj: dict) -> str:
        """message.content가 str 또는 list 배열 모두 처리."""
        content = message_obj.get("message", {}).get("content") or message_obj.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    if item.get("type") == "text":
                        parts.append(item.get("text", ""))
            return " ".join(parts)
        return ""

    def build_summary_prompt(self, messages: list[dict], meta: SessionMeta) -> str:
        """요약 요청 프롬프트 생성."""
        lines: list[str] = [
            f"세션 ID: {meta.id}",
            f"소스 타입: {meta.source_type}" + (f" (agent: {meta.agent_name})" if meta.agent_name else ""),
            f"수정일시: {meta.mtime.isoformat()}",
        ]
        if meta.cwd:
            lines.append(f"작업 디렉토리: {meta.cwd}")
        if meta.git_branch:
            lines.append(f"Git 브랜치: {meta.git_branch}")
        lines.append("")
        lines.append("--- 대화 내용 ---")

        for msg in messages:
            role = msg.get("type", "unknown")
            content = self.extract_content(msg)
            if content:
                lines.append(f"[{role}] {content[:500]}")

        lines.append("")
        lines.append(
            "위 Claude Code 세션을 한국어로 간결하게 요약해주세요. "
            "주요 작업 내용, 구현하거나 수정한 기능, 해결한 문제를 중심으로 3-5문장으로 작성하세요."
        )
        return "\n".join(lines)
