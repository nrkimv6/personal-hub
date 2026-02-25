"""plan 문서 관리 서비스"""

import asyncio
import json
import logging
import re
import redis
import shutil
from datetime import date
from pathlib import Path
from typing import List, Optional

from app.modules.dev_runner.config import config
from app.modules.dev_runner.services.log_service import LOG_CHANNEL, REDIS_HOST, REDIS_PORT
from app.modules.dev_runner.schemas import (
    PlanFileResponse, PlanProgressResponse,
    PlanDetailResponse, PlanPhaseResponse, PlanItemResponse,
    RegisteredPathResponse,
)

logger = logging.getLogger(__name__)

# 모듈 레벨 Redis 연결 (lazy — 첫 호출 시 생성)
_redis_client: Optional[redis.Redis] = None


def _get_redis() -> Optional[redis.Redis]:
    global _redis_client
    if _redis_client is None:
        try:
            _redis_client = redis.Redis(
                host=REDIS_HOST, port=REDIS_PORT,
                decode_responses=True, socket_connect_timeout=2
            )
        except Exception:
            return None
    return _redis_client


def _publish_log(tag: str, message: str):
    """Redis pub/sub으로 로그 publish (LogViewer에 실시간 표시)"""
    from datetime import datetime
    try:
        r = _get_redis()
        if r:
            ts = datetime.now().strftime("%H:%M:%S")
            r.publish(LOG_CHANNEL, f"[{ts}] [{tag}] {message}")
    except Exception:
        pass  # Redis 미연결 시 무시


class PlanService:
    """plan 문서 탐색 및 파싱 서비스"""

    def __init__(self):
        self._registered_paths: List[dict] = []  # {"path": str, "type": "plan"|"archive"}
        self._ignored_plans: List[str] = []
        self._migrate_to_registered_paths()
        self._load_registered_paths()
        self._load_ignored_plans()

    # ========== 경로 저장/로드 ==========

    def _migrate_to_registered_paths(self):
        """external_plans.json → registered_paths.json 마이그레이션 (1회성)
        + 문자열 배열 → 객체 배열 마이그레이션 (스키마 변경 대응)
        """
        reg_path = config.REGISTERED_PATHS_FILE

        if reg_path.exists():
            # 기존 파일이 문자열 배열이면 객체 배열로 마이그레이션
            try:
                data = json.loads(reg_path.read_text(encoding="utf-8"))
                if data and isinstance(data[0], str):
                    migrated = [{"path": p, "type": "plan"} for p in data]
                    reg_path.write_text(json.dumps(migrated, ensure_ascii=False, indent=2), encoding="utf-8")
                    logger.info(f"[마이그레이션] 문자열→객체 배열 변환 완료 ({len(migrated)}개)")
            except Exception:
                pass
            return

        paths: List[str] = []

        # 기존 external_plans.json에서 가져오기
        ext_path = config.EXTERNAL_PLANS_FILE
        if ext_path.exists():
            try:
                paths = json.loads(ext_path.read_text(encoding="utf-8"))
                logger.info(f"[마이그레이션] external_plans.json에서 {len(paths)}개 경로 로드")
            except Exception:
                paths = []

        # WTOOLS_BASE_DIR 시드: 존재하는 프로젝트 plan 폴더를 자동 등록
        existing = set(paths)
        base = config.WTOOLS_BASE_DIR
        if base.exists():
            # common/docs/plan
            common_dir = base / config.PLAN_DIR
            if common_dir.exists():
                resolved = str(common_dir.resolve())
                if resolved not in existing:
                    paths.append(resolved)
                    existing.add(resolved)

            # 각 프로젝트의 docs/plan
            for project in config.PROJECT_DIRS:
                project_dir = base / project / "docs" / "plan"
                if project_dir.exists():
                    resolved = str(project_dir.resolve())
                    if resolved not in existing:
                        paths.append(resolved)
                        existing.add(resolved)

            logger.info(f"[마이그레이션] WTOOLS 시드 완료 — 총 {len(paths)}개 경로")

        # 객체 배열로 저장
        if paths:
            entries = [{"path": p, "type": "plan"} for p in paths]
            reg_path.parent.mkdir(parents=True, exist_ok=True)
            reg_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info(f"[마이그레이션] registered_paths.json 생성 완료 ({len(entries)}개)")

    def _load_registered_paths(self):
        """등록된 경로 목록 로드 (JSON 파일) — 객체 배열 {"path", "type"}"""
        path = config.REGISTERED_PATHS_FILE
        if path.exists():
            try:
                self._registered_paths = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                self._registered_paths = []

    def _save_registered_paths(self):
        """등록된 경로 목록 저장 — 객체 배열 {"path", "type"}"""
        path = config.REGISTERED_PATHS_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self._registered_paths, ensure_ascii=False, indent=2), encoding="utf-8")

    def _get_registered_path_strs(self) -> List[str]:
        """등록 경로를 문자열 목록으로 반환 (내부 탐색용)"""
        return [entry["path"] for entry in self._registered_paths]

    def _load_ignored_plans(self):
        """수동 무시 plan 목록 로드"""
        path = config.IGNORED_PLANS_FILE
        if path.exists():
            try:
                self._ignored_plans = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                self._ignored_plans = []

    def _save_ignored_plans(self):
        """수동 무시 plan 목록 저장"""
        path = config.IGNORED_PLANS_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self._ignored_plans, ensure_ascii=False, indent=2), encoding="utf-8")

    # ========== 경로 관리 ==========

    def add_to_ignore(self, plan_path: str) -> bool:
        """plan을 수동 무시 목록에 추가"""
        resolved = str(Path(plan_path).resolve())
        if resolved not in self._ignored_plans:
            self._ignored_plans.append(resolved)
            self._save_ignored_plans()
            return True
        return False

    def remove_from_ignore(self, plan_path: str) -> bool:
        """plan을 수동 무시 목록에서 제거"""
        resolved = str(Path(plan_path).resolve())
        if resolved in self._ignored_plans:
            self._ignored_plans.remove(resolved)
            self._save_ignored_plans()
            return True
        return False

    def add_path(self, plan_path: str, path_type: str = "plan") -> bool:
        """등록 경로 추가 (영구 저장)

        Args:
            plan_path: 등록할 경로
            path_type: "plan" | "archive" (기본값: "plan")
        """
        resolved = str(Path(plan_path).resolve())
        existing_paths = self._get_registered_path_strs()
        if resolved not in existing_paths:
            self._registered_paths.append({"path": resolved, "type": path_type})
            self._save_registered_paths()
            return True
        return False

    def remove_path(self, plan_path: str) -> bool:
        """등록 경로 제거"""
        resolved = str(Path(plan_path).resolve())
        for i, entry in enumerate(self._registered_paths):
            if entry["path"] == resolved:
                self._registered_paths.pop(i)
                self._save_registered_paths()
                return True
        return False

    # ========== plan 목록 ==========

    def list_plans(self, include_ignored: bool = False) -> List[PlanFileResponse]:
        """
        plan 목록 조회 — 등록된 경로(폴더/파일) 순회

        모든 경로를 동등하게 취급 (고정/외부 구분 없음)
        """
        seen: set[str] = set()
        results: List[PlanFileResponse] = []

        for entry in self._registered_paths:
            if entry.get("type") == "archive":
                continue
            reg_path = entry["path"]
            p = Path(reg_path)
            if not p.exists():
                continue
            if p.is_dir():
                self._scan_plan_dir(p, seen, results, include_ignored, path_type="folder")
            elif p.is_file():
                if str(p) not in seen:
                    seen.add(str(p))
                    status = self.get_plan_status(p)
                    progress = self.get_plan_progress(p)
                    is_ignored = self._is_ignored_plan(p, status, progress)
                    if include_ignored or not is_ignored:
                        results.append(
                            PlanFileResponse(
                                path=str(p),
                                filename=p.name,
                                status=status,
                                progress=progress,
                                source=self._resolve_source(p.parent),
                                ignored=is_ignored,
                                path_type="file",
                            )
                        )

        results.sort(key=lambda x: x.filename, reverse=True)
        return results

    def list_ignored_plans(self) -> List[PlanFileResponse]:
        """무시된(완료/빈) plan 목록만 조회"""
        all_plans = self.list_plans(include_ignored=True)
        return [p for p in all_plans if p.ignored]

    def _resolve_source(self, path: Path) -> str:
        """경로에서 source 자동 결정

        - .../프로젝트/docs/plan → 프로젝트명
        - .../common/docs/plan → "common"
        - .../폴더명 → 폴더명
        """
        parts = path.parts
        for i, part in enumerate(parts):
            if part == "docs" and i + 1 < len(parts) and parts[i + 1] == "plan":
                # docs/plan 직전 디렉토리 = 프로젝트명
                if i > 0:
                    return parts[i - 1]
                return "common"
        # docs/plan 패턴 없음 → 폴더명 자체
        return path.name or "unknown"

    def _scan_plan_dir(
        self,
        plan_dir: Path,
        seen: set,
        results: List[PlanFileResponse],
        include_ignored: bool,
        path_type: Optional[str] = None,
    ):
        """plan 디렉토리 스캔

        Args:
            plan_dir: 스캔할 디렉토리
            seen: 이미 처리된 경로 집합 (중복 방지)
            results: 결과 목록 (append)
            include_ignored: True이면 무시된 plan도 포함
            path_type: "folder" | None — PlanFileResponse.path_type에 설정할 값
        """
        if not plan_dir.exists():
            return

        source = self._resolve_source(plan_dir)

        for plan_file in plan_dir.glob("*.md"):
            if plan_file.stem.endswith("_todo"):
                pass  # _todo.md는 항상 표시 (체크박스가 있는 작업 파일)
            else:
                # 대응 _todo.md가 있으면 메인 파일 스킵 (_todo가 대표)
                todo_file = plan_file.parent / (plan_file.stem + "_todo.md")
                if todo_file.exists():
                    continue
            key = str(plan_file)
            if key in seen:
                continue
            seen.add(key)

            status = self.get_plan_status(plan_file)
            progress = self.get_plan_progress(plan_file)
            is_ignored = self._is_ignored_plan(plan_file, status, progress)

            if include_ignored or not is_ignored:
                results.append(
                    PlanFileResponse(
                        path=str(plan_file),
                        filename=plan_file.name,
                        status=status,
                        progress=progress,
                        source=source,
                        ignored=is_ignored,
                        path_type=path_type,
                    )
                )

    # 자동 무시 대상 상태 (정확히 일치해야 함)
    _IGNORED_STATUSES = {"보류"}
    # 완료 계열 상태 (아카이브 허용 + 목록 숨김)
    _DONE_STATUSES = {"구현완료", "완료", "수정 완료", "배포완료", "수정완료", "검토완료"}

    def _is_ignored_plan(self, path: Path, status: str, progress: PlanProgressResponse) -> bool:
        """plan이 무시 대상인지 판단"""
        # 수동 무시 목록
        if str(path.resolve()) in self._ignored_plans:
            return True
        # 보류 상태
        if status in self._IGNORED_STATUSES:
            return True
        # 완료 계열 상태
        if status in self._DONE_STATUSES:
            return True
        # 모든 체크박스 완료
        if progress.total > 0 and progress.done == progress.total:
            return True
        return False

    # ========== plan 파싱 ==========

    def get_plan_progress(self, path: Path) -> PlanProgressResponse:
        """plan 진행률 파싱"""
        if not path.exists():
            return PlanProgressResponse(done=0, total=0, percent=0)

        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

            content = self._remove_code_blocks(content)
            checkbox_pattern = r"^(?:\d+\.|-)\s*\[([ x→])\]"
            matches = re.findall(checkbox_pattern, content, re.MULTILINE)

            total = len(matches)
            done = sum(1 for m in matches if m == "x")
            percent = int(done / total * 100) if total > 0 else 0

            return PlanProgressResponse(done=done, total=total, percent=percent)
        except Exception:
            return PlanProgressResponse(done=0, total=0, percent=0)

    @staticmethod
    def _strip_markdown_inline(text: str) -> str:
        """마크다운 인라인 스타일 제거 (**굵게**, *기울임*, ~~취소선~~, `코드`)"""
        return re.sub(r'[*_~`]+', '', text).strip()

    def get_plan_status(self, path: Path) -> str:
        """plan 상태 파싱 (> 상태: ...), 없으면 유형으로 판단"""
        if not path.exists():
            return "unknown"

        try:
            doc_type = None
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                for i, line in enumerate(f):
                    if i >= 20:
                        break
                    match = re.match(r">\s*상태:\s*(.+)", line)
                    if match:
                        return self._strip_markdown_inline(match.group(1))
                    # - **상태**: ... (리스트+bold 형식)
                    match2 = re.match(r"-\s*\*{0,2}상태\*{0,2}:\s*(.+)", line)
                    if match2:
                        return self._strip_markdown_inline(match2.group(1))
                    type_match = re.match(r">\s*유형:\s*(.+)", line)
                    if type_match:
                        doc_type = self._strip_markdown_inline(type_match.group(1))
            # 상태 라인이 없고, 보고서 유형이면 완료로 간주
            if doc_type and re.search(r'보고서|report', doc_type, re.IGNORECASE):
                return "완료"
            # 파일명에 -report, -postmortem 포함 시 완료로 간주
            stem = path.stem.lower()
            if '-report' in stem or '-postmortem' in stem:
                return "완료"
            return "unknown"
        except Exception:
            return "unknown"

    def _find_todo_file(self, plan_path: Path) -> Optional[Path]:
        """plan 경로에서 대응하는 _todo.md 파일 탐색"""
        todo_name = plan_path.stem + "_todo.md"
        todo_path = plan_path.parent / todo_name
        if todo_path.exists():
            return todo_path
        return None

    def parse_plan_items(self, path: Path) -> PlanDetailResponse:
        """plan 파일을 Phase별 항목으로 파싱"""
        # _todo 파일이 있으면 우선 사용
        todo_file = self._find_todo_file(path)
        parse_path = todo_file if todo_file else path

        content = parse_path.read_text(encoding="utf-8", errors="ignore")
        lines = content.split("\n")

        phases: List[PlanPhaseResponse] = []
        current_phase_name = "기타"
        current_items: List[PlanItemResponse] = []
        current_parent: Optional[PlanItemResponse] = None

        # 파일 경로 패턴: `path/to/file.ext`
        file_path_pattern = re.compile(r'`([^`]+\.[a-zA-Z]+)`')

        for line in lines:
            # Phase 헤더 감지
            phase_match = re.match(r'^#{2,3}\s+Phase\s+\d+[:\s—–-]*(.*)', line)
            if phase_match:
                # 이전 phase 저장
                if current_items:
                    done = sum(1 for i in current_items if i.checked)
                    total_children = sum(len(i.children) for i in current_items)
                    done_children = sum(1 for i in current_items for c in i.children if c.checked)
                    phases.append(PlanPhaseResponse(
                        name=current_phase_name,
                        items=current_items,
                        done_count=done + done_children,
                        total_count=len(current_items) + total_children,
                    ))
                current_phase_name = phase_match.group(0).lstrip("#").strip()
                current_items = []
                current_parent = None
                continue

            # 번호 체크박스 (상위): 1. [ ] or 1. [x]
            num_match = re.match(r'^(\d+)\.\s*\[([ x→])\]\s*(.*)', line)
            if num_match:
                text = num_match.group(3).strip()
                fp = file_path_pattern.search(text)
                item = PlanItemResponse(
                    level=0,
                    text=text,
                    checked=num_match.group(2) == 'x',
                    file_path=fp.group(1) if fp else None,
                )
                current_items.append(item)
                current_parent = item
                continue

            # 대시 체크박스: - [ ] or - [x] (최상위 + 하위 모두)
            dash_match = re.match(r'^(\s*)-\s*\[([ x→])\]\s*(.*)', line)
            if dash_match:
                indent = len(dash_match.group(1))
                text = dash_match.group(3).strip()
                fp = file_path_pattern.search(text)
                if indent > 0 and current_parent is not None:
                    # 들여쓰기 있음 → 하위 항목
                    child = PlanItemResponse(
                        level=1,
                        text=text,
                        checked=dash_match.group(2) == 'x',
                        file_path=fp.group(1) if fp else None,
                    )
                    current_parent.children.append(child)
                else:
                    # 들여쓰기 없음 → 상위 항목
                    item = PlanItemResponse(
                        level=0,
                        text=text,
                        checked=dash_match.group(2) == 'x',
                        file_path=fp.group(1) if fp else None,
                    )
                    current_items.append(item)
                    current_parent = item

        # 마지막 phase 저장
        if current_items:
            done = sum(1 for i in current_items if i.checked)
            total_children = sum(len(i.children) for i in current_items)
            done_children = sum(1 for i in current_items for c in i.children if c.checked)
            phases.append(PlanPhaseResponse(
                name=current_phase_name,
                items=current_items,
                done_count=done + done_children,
                total_count=len(current_items) + total_children,
            ))

        status = self.get_plan_status(path)
        progress = self.get_plan_progress(parse_path)

        return PlanDetailResponse(
            path=str(path),
            filename=path.name,
            status=status,
            phases=phases,
            progress=progress,
        )

    # ========== done 처리 (Python 네이티브) ==========

    COMMIT_SH = Path("D:/work/project/tools/common/commit.sh")

    @staticmethod
    def _remove_code_blocks(content: str) -> str:
        """코드블록/인라인 코드 제거 (체크박스 오인식 방지)"""
        content = re.sub(r'```.*?```', '', content, flags=re.DOTALL)
        content = re.sub(r'`[^`\n]+`', '', content)
        return content

    @staticmethod
    def _extract_pending_checkboxes(content: str) -> List[str]:
        """문서 전체에서 미완료 체크박스 텍스트 추출 (코드블록 제외)"""
        cleaned = PlanService._remove_code_blocks(content)
        matches = re.findall(r'^[-*]\s*\[ \]\s*(.+)$', cleaned, re.MULTILINE)
        return [PlanService._strip_markdown_inline(m) for m in matches]

    @staticmethod
    def _update_manual_tasks(
        project_dir: Path, items: List[str], plan_filename: str
    ) -> None:
        """미완료 체크박스를 MANUAL_TASKS.md로 이관"""
        manual_path = project_dir / "MANUAL_TASKS.md"
        today = date.today().isoformat()

        if manual_path.exists():
            existing = manual_path.read_text(encoding="utf-8")
        else:
            existing = ""

        # 중복 체크: 이미 이 plan에서 이관된 항목이 있으면 스킵
        if f"from: {plan_filename}" in existing:
            return

        # 새 항목 생성
        new_lines = []
        for item in items:
            new_lines.append(f"- [ ] {item} — from: {plan_filename} ({today})")

        if not existing:
            # 파일 신규 생성
            content = (
                "# MANUAL_TASKS\n\n"
                "> 자동화가 어렵거나 사람의 판단이 필요한 수동 작업 목록\n\n"
                "## 미완료\n\n"
                + "\n".join(new_lines) + "\n\n"
                "## 완료\n"
            )
            manual_path.write_text(content, encoding="utf-8")
        else:
            # 기존 파일의 ## 미완료 섹션 직후에 삽입
            lines = existing.splitlines()
            insert_idx = None
            for i, line in enumerate(lines):
                if line.strip() == "## 미완료":
                    insert_idx = i + 1
                    # 빈 줄 건너뜀
                    while insert_idx < len(lines) and lines[insert_idx].strip() == "":
                        insert_idx += 1
                    break
            if insert_idx is not None:
                for j, item_line in enumerate(new_lines):
                    lines.insert(insert_idx + j, item_line)
                manual_path.write_text("\n".join(lines), encoding="utf-8")

    @staticmethod
    def _extract_plan_title(content: str) -> str:
        """첫 번째 # 헤더에서 제목 추출"""
        match = re.search(r'^#\s+(.+)', content, re.MULTILINE)
        if match:
            return match.group(1).strip()
        return "Unknown Plan"

    @staticmethod
    def _resolve_project_dir(plan_path: str) -> Optional[Path]:
        """plan 경로에서 프로젝트 디렉토리 추론

        - docs/plan 패턴 감지 → plan 디렉토리의 3단계 위 (file → plan → docs → project_root)
        - 패턴 불일치 시 파일 기준 상위 3단계 fallback
        """
        p = Path(plan_path).resolve()
        parts = p.parts
        for i, part in enumerate(parts):
            if part == "plan" and i > 0 and parts[i - 1] == "docs":
                # parts[0..i-2] = project root
                project_root = Path(*parts[:i - 1])
                if project_root.exists():
                    return project_root
        # fallback: 파일 기준 상위 3단계
        try:
            candidate = p.parent.parent.parent
            if candidate.exists():
                return candidate
        except Exception:
            pass
        return None

    @staticmethod
    def _update_plan_headers(content: str, total: int) -> str:
        """상태→구현완료, 진행률→100%, [→ID]→[x] 치환, 푸터 갱신"""
        content = re.sub(r'^(>\s*상태:\s*).*$', r'\1구현완료', content, flags=re.MULTILINE)
        content = re.sub(
            r'^(>\s*진행률:\s*)[\d/\s()%]+$',
            f'> 진행률: {total}/{total} (100%)',
            content, flags=re.MULTILINE
        )
        # [→ID] 형태 → [x]
        content = re.sub(r'\[→[^\]]*\]', '[x]', content)
        # 푸터 갱신: *상태: ... | 진행률: ...*
        content = re.sub(
            r'\*상태:[^|*]+\|[^*]*진행률:[^*]*\*',
            f'*상태: 구현완료 | 진행률: {total}/{total} (100%)*',
            content
        )
        return content

    async def _archive_plan(self, plan_path: str, content: str) -> Path:
        """완료일 헤더 삽입 후 git mv로 archive 디렉토리로 이동"""
        p = Path(plan_path)
        today = date.today().isoformat()

        # 완료일 헤더 삽입 (> 상태: 줄 다음에)
        lines = content.splitlines(keepends=True)
        inserted = False
        for i, line in enumerate(lines):
            if re.match(r'^>\s*상태:', line):
                lines.insert(i + 1, f'> 완료일: {today}\n')
                inserted = True
                break
        if not inserted:
            for i, line in enumerate(lines):
                if line.startswith('#'):
                    lines.insert(i + 1, f'\n> 완료일: {today}\n')
                    break
        final_content = "".join(lines)

        # 1. 원본 파일에 수정된 내용 덮어쓰기 (git mv 전에 내용 반영)
        p.write_text(final_content, encoding="utf-8")

        # 2. archive 디렉토리 생성
        archive_dir = p.parent.parent / "archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive_path = archive_dir / p.name

        # 3. git mv로 이동 (rename 이력 보존 + staging 자동)
        mv_proc = await asyncio.create_subprocess_exec(
            "git", "mv", str(p), str(archive_path),
            cwd=str(p.parent),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await mv_proc.communicate()
        if mv_proc.returncode != 0:
            # git mv 실패 시 fallback: 파일시스템 이동
            archive_path.write_text(final_content, encoding="utf-8")
            p.unlink()

        return archive_path

    @staticmethod
    def _update_todo_done(project_dir: Path, plan_title: str) -> None:
        """TODO.md에서 plan_title 관련 항목 제거, DONE.md 상단에 추가"""
        today = date.today().isoformat()

        # TODO.md: plan_title을 포함하는 체크박스 줄 제거
        todo_path = project_dir / "TODO.md"
        if todo_path.exists():
            lines = todo_path.read_text(encoding="utf-8").splitlines(keepends=True)
            filtered = [
                l for l in lines
                if not (plan_title in l and re.search(r'\[[ x→]\]', l))
            ]
            if len(filtered) < len(lines):
                todo_path.write_text("".join(filtered), encoding="utf-8")

        # DONE.md 상단에 추가
        done_path = project_dir / "docs" / "DONE.md"
        done_path.parent.mkdir(parents=True, exist_ok=True)
        new_entry = f"- [x] {today}: {plan_title}\n"

        if done_path.exists():
            existing = done_path.read_text(encoding="utf-8")
            header_match = re.match(r'(#[^\n]+\n\n?)', existing)
            if header_match:
                pos = header_match.end()
                done_path.write_text(existing[:pos] + new_entry + existing[pos:], encoding="utf-8")
            else:
                done_path.write_text(new_entry + existing, encoding="utf-8")
        else:
            done_path.write_text(f"# DONE (최근 20개)\n\n{new_entry}", encoding="utf-8")

    @staticmethod
    def _archive_done_if_needed(done_path: Path) -> None:
        """DONE.md 항목 5개 초과 시 월별 아카이브"""
        if not done_path.exists():
            return

        content = done_path.read_text(encoding="utf-8")
        lines = content.splitlines(keepends=True)
        item_lines = [l for l in lines if re.match(r'^-\s*\[', l)]

        if len(item_lines) <= 5:
            return

        keep = item_lines[:5]
        overflow = item_lines[5:]

        today = date.today()
        archive_dir = done_path.parent / "history"
        archive_dir.mkdir(parents=True, exist_ok=True)
        week_str = f"{today.year}-W{today.isocalendar()[1]:02d}"
        archive_path = archive_dir / f"DONE-{week_str}.md"

        if archive_path.exists():
            archive_path.write_text(
                archive_path.read_text(encoding="utf-8") + "".join(overflow),
                encoding="utf-8"
            )
        else:
            archive_path.write_text(
                f"# DONE Archive {week_str}\n\n" + "".join(overflow),
                encoding="utf-8"
            )

        # DONE.md 갱신 (최근 5개만 유지)
        header_match = re.match(r'(#[^\n]+\n\n?)', content)
        header = header_match.group(1) if header_match else "# DONE (최근 20개)\n\n"
        done_path.write_text(header + "".join(keep), encoding="utf-8")

    async def _git_commit(
        self, project_dir: Optional[Path], files_to_add: List[Path], commit_msg: str
    ) -> str:
        """git add + commit.sh 호출"""
        if not self.COMMIT_SH.exists():
            return f"commit.sh not found: {self.COMMIT_SH}"

        # 존재하는 파일(신규/수정) + 삭제된 파일(git mv로 이미 staged된 경우도 포함)을 모두 add
        # git add는 삭제된 파일 경로도 처리 가능 (staging에 반영)
        existing_files = [str(f) for f in files_to_add if f.exists()]
        deleted_files = [str(f) for f in files_to_add if not f.exists()]
        all_files = existing_files + deleted_files
        if not all_files:
            return "커밋할 파일 없음"

        cwd = str(project_dir) if project_dir and project_dir.exists() else None

        # git add (존재하는 파일 먼저, 삭제된 파일은 별도 처리)
        add_proc = await asyncio.create_subprocess_exec(
            "git", "add", *all_files,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        await add_proc.communicate()

        # commit.sh
        commit_proc = await asyncio.create_subprocess_exec(
            "bash", str(self.COMMIT_SH), commit_msg,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await asyncio.wait_for(commit_proc.communicate(), timeout=60)
        return stdout.decode("utf-8", errors="replace") if stdout else ""

    async def run_done(self, plan_path: str) -> dict:
        """Python 네이티브 plan 완료 처리 (아카이브, TODO→DONE, git commit)"""
        path = Path(plan_path)
        if not path.exists():
            return {"success": False, "message": f"Plan file not found: {plan_path}", "output": None,
                    "remaining_tasks": 0, "total_tasks": 0, "plan_status": ""}

        pre_progress = self.get_plan_progress(path)
        pre_status = self.get_plan_status(path)

        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
            title = self._extract_plan_title(content)
            total = pre_progress.total

            # 1. 헤더/푸터 갱신
            updated_content = self._update_plan_headers(content, total)

            # 2. 미완료 체크박스 → MANUAL_TASKS.md 이관
            project_dir = self._resolve_project_dir(plan_path)
            pending_items = self._extract_pending_checkboxes(updated_content)
            has_manual = False
            if pending_items and project_dir:
                self._update_manual_tasks(project_dir, pending_items, path.name)
                has_manual = True

            # 3. 아카이브 이동
            archive_path = await self._archive_plan(plan_path, updated_content)

            # 4. TODO.md / DONE.md 업데이트
            if project_dir:
                self._update_todo_done(project_dir, title)
                done_path = project_dir / "docs" / "DONE.md"
                self._archive_done_if_needed(done_path)

            # 5. git commit
            files_to_commit: List[Path] = [archive_path]
            if project_dir:
                files_to_commit += [
                    project_dir / "TODO.md",
                    project_dir / "docs" / "DONE.md",
                ]
                if has_manual:
                    files_to_commit.append(project_dir / "MANUAL_TASKS.md")
            commit_output = await self._git_commit(
                project_dir, files_to_commit, f"docs: {title} 완료 처리"
            )

            self.sync_plans()

            # DB 기록: plan_records에 archive 완료 기록
            try:
                from app.database import SessionLocal
                from app.modules.dev_runner.services.plan_record_service import PlanRecordService
                with SessionLocal() as db:
                    svc = PlanRecordService(db)
                    svc.mark_archived(plan_path, str(archive_path))
                    db.commit()
            except Exception as db_err:
                logger.warning(f"plan_record DB 기록 실패 (무시): {db_err}")

            return {
                "success": True,
                "message": "완료 처리 성공",
                "output": f"아카이브: {archive_path}\n{commit_output}",
                "remaining_tasks": pre_progress.total - pre_progress.done,
                "total_tasks": pre_progress.total,
                "plan_status": pre_status,
            }

        except Exception as e:
            logger.error(f"run_done 실패: {e}")
            return {"success": False, "message": str(e), "output": None,
                    "remaining_tasks": 0, "total_tasks": 0, "plan_status": ""}

    # ========== 일괄 완료 ==========

    def verify_completion(self, plan_path: Path) -> "VerifyResult":
        """코드베이스와 계획서를 대조하여 완료 여부 판정"""
        from app.modules.dev_runner.schemas import VerifyResult

        # archive 경로이면 즉시 can_done=False
        if "archive" in str(plan_path):
            return VerifyResult(total=0, verified=0, unverified_items=[], percent=0.0, can_done=False)

        detail = self.parse_plan_items(plan_path)

        total = 0
        verified = 0
        unverified_items: list[str] = []

        def process_item(item) -> None:
            nonlocal total, verified
            total += 1
            if item.file_path:
                if Path(item.file_path).exists():
                    verified += 1
                else:
                    unverified_items.append(item.text)
            else:
                if item.checked:
                    verified += 1
                else:
                    unverified_items.append(item.text)
            for child in item.children:
                process_item(child)

        for phase in detail.phases:
            for item in phase.items:
                process_item(item)

        percent = round(verified / total * 100, 1) if total > 0 else 0.0
        can_done = total > 0 and verified == total

        return VerifyResult(
            total=total,
            verified=verified,
            unverified_items=unverified_items,
            percent=percent,
            can_done=can_done,
        )

    def _can_done(self, plan: PlanFileResponse) -> bool:
        """plan이 done 처리 가능한지 판단 — 체크박스 전체 완료 OR 상태 헤더 완료 계열"""
        if "archive" in plan.path:
            return False
        if plan.progress.total > 0 and plan.progress.done == plan.progress.total:
            return True
        if plan.status in self._DONE_STATUSES:
            return True
        return False

    async def batch_done(self) -> dict:
        """완료 가능한 plan을 일괄 done 처리"""
        all_plans = self.list_plans(include_ignored=True)
        targets = [p for p in all_plans if self._can_done(p)]

        if not targets:
            return {"total": 0, "success": 0, "failed": 0, "results": []}

        results = []
        success_count = 0
        failed_count = 0

        filenames = ",".join(p.filename for p in targets)
        _publish_log("BATCH", f"PLAN_LIST {filenames}")

        for plan in targets:
            _publish_log("BATCH", f"PLAN_START {plan.filename}")
            result = await self.run_done(plan.path)
            results.append({
                "path": plan.path,
                "filename": plan.filename,
                "success": result["success"],
                "message": result["message"],
            })
            if result["success"]:
                success_count += 1
                _publish_log("BATCH", f"PLAN_DONE {plan.filename}")
            else:
                failed_count += 1
                _publish_log("BATCH", f"PLAN_FAILED {plan.filename}")  # 버그 수정: PLAN_DONE → PLAN_FAILED
                _publish_log("ERROR", f"{plan.filename}: {result['message']}")

        _publish_log("INFO", f"일괄완료 종료: {success_count}개 성공, {failed_count}개 실패")

        return {
            "total": len(targets),
            "success": success_count,
            "failed": failed_count,
            "results": results,
        }

    # ========== 상태 변경 ==========

    def set_plan_status(self, plan_path: str, new_status: str) -> bool:
        """plan 파일의 '> 상태: ...' 줄을 변경 (없으면 제목 아래에 추가)"""
        path = Path(plan_path)
        if not path.exists():
            return False

        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)
        status_pattern = re.compile(r"^>\s*상태:\s*(.+)")
        found = False

        for i, line in enumerate(lines):
            if status_pattern.match(line):
                lines[i] = f"> 상태: {new_status}\n"
                found = True
                break

        if not found:
            # 제목(#) 바로 아래에 삽입
            for i, line in enumerate(lines):
                if line.startswith("#"):
                    lines.insert(i + 1, f"\n> 상태: {new_status}\n")
                    found = True
                    break

        if found:
            path.write_text("".join(lines), encoding="utf-8")
        return found

    # ========== 동기화 ==========

    def sync_plans(self) -> dict:
        """plan 동기화 — 이전 상태와 비교하여 변경 요약 반환"""
        # 이전 상태 스냅샷 (path → {status, done, total})
        old_plans = {p.path: p for p in self.list_plans(include_ignored=True)}
        old_keys = set(old_plans.keys())

        # 디스크에서 다시 스캔 (캐시 무효화)
        self._load_registered_paths()
        new_plans_list = self.list_plans(include_ignored=True)
        new_plans = {p.path: p for p in new_plans_list}
        new_keys = set(new_plans.keys())

        added = len(new_keys - old_keys)
        removed = len(old_keys - new_keys)

        updated = 0
        for key in old_keys & new_keys:
            old_p = old_plans[key]
            new_p = new_plans[key]
            if (old_p.status != new_p.status
                    or old_p.progress.done != new_p.progress.done
                    or old_p.progress.total != new_p.progress.total):
                updated += 1

        return {
            "synced": len(new_plans_list),
            "added": added,
            "removed": removed,
            "updated": updated,
        }

    # ========== 외부 경로 추출 ==========

    def get_ignored_plan_paths(self) -> List[str]:
        """UI와 동일한 기준으로 무시 대상 plan 절대경로 리스트 반환

        수동 목록(ignored_plans.json) + 상태 완료/보류 + 체크박스 전체 완료
        """
        ignored = set(self._ignored_plans)

        for entry in self._registered_paths:
            p = Path(entry["path"])
            if not p.exists():
                continue
            files = p.glob("*.md") if p.is_dir() else [p]
            for plan_file in files:
                if not plan_file.is_file():
                    continue
                resolved = str(plan_file.resolve())
                if resolved in ignored:
                    continue
                status = self.get_plan_status(plan_file)
                progress = self.get_plan_progress(plan_file)
                if self._is_ignored_plan(plan_file, status, progress):
                    ignored.add(resolved)

        return list(ignored)

    def get_extra_plan_dirs(self) -> List[str]:
        """registered_paths 중 WTOOLS_BASE_DIR 하위가 아닌 폴더 경로만 반환"""
        wtools_prefix = str(config.WTOOLS_BASE_DIR.resolve())
        extra_dirs = []
        for entry in self._registered_paths:
            reg_path = entry["path"]
            p = Path(reg_path)
            if not p.is_dir():
                continue
            resolved = str(p.resolve())
            if not resolved.startswith(wtools_prefix):
                extra_dirs.append(resolved)
        return extra_dirs

    # ========== 등록 경로 관리 ==========

    def list_registered_paths(self) -> List[RegisteredPathResponse]:
        """등록된 경로 목록 조회 (타입 + plan_count + path_type 포함)"""
        result = []
        for entry in self._registered_paths:
            reg_path = entry["path"]
            path_type = entry.get("type", "plan")
            p = Path(reg_path)
            if p.is_dir():
                plan_count = sum(
                    1 for f in p.glob("*.md")
                    if f.stem.endswith("_todo")
                    or not (f.parent / (f.stem + "_todo.md")).exists()
                ) if p.exists() else 0
                result.append(RegisteredPathResponse(path=reg_path, type="folder", plan_count=plan_count, path_type=path_type))
            else:
                result.append(RegisteredPathResponse(path=reg_path, type="file", plan_count=1 if p.exists() else 0, path_type=path_type))
        return result

    def validate_path(self, path: str) -> bool:
        """경로 화이트리스트 검증"""
        path_obj = Path(path).resolve()
        path_str = str(path_obj)

        for allowed in config.ALLOWED_PATHS:
            if path_str.startswith(allowed):
                return True
        return False


# 싱글톤 인스턴스
plan_service = PlanService()

__all__ = ['plan_service', 'PlanService']
