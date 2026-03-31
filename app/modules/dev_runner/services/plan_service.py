"""plan 문서 관리 서비스"""

import asyncio
import json
import logging
import re
import redis
import shutil
import subprocess
import time
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
        # archive 캐시: {dir_path: {"mtime": float, "results": [PlanFileResponse]}}
        # include_ignored=True 경로에서만 활용 (기본 리스트는 archive 스캔 자체를 스킵)
        self._archive_cache: dict[str, dict] = {}
        # plan 전체 목록 캐시 (startup 시 빌드, mutation 시 무효화)
        self._plans_cache: Optional[List[PlanFileResponse]] = None
        self._plans_cache_with_ignored: Optional[List[PlanFileResponse]] = None
        self._plans_cache_time: float = 0  # 캐시 빌드 시각 (time.monotonic)
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
            self.invalidate_plans_cache()
            return True
        return False

    def remove_from_ignore(self, plan_path: str) -> bool:
        """plan을 수동 무시 목록에서 제거"""
        resolved = str(Path(plan_path).resolve())
        if resolved in self._ignored_plans:
            self._ignored_plans.remove(resolved)
            self._save_ignored_plans()
            self.invalidate_plans_cache()
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
            self.invalidate_plans_cache()
            return True
        return False

    def remove_path(self, plan_path: str) -> bool:
        """등록 경로 제거"""
        resolved = str(Path(plan_path).resolve())
        for i, entry in enumerate(self._registered_paths):
            if entry["path"] == resolved:
                self._registered_paths.pop(i)
                self._save_registered_paths()
                self.invalidate_plans_cache()
                return True
        return False

    # ========== plan 목록 ==========

    def invalidate_plans_cache(self):
        """plan 목록 캐시 무효화 — mutation 후 호출"""
        self._plans_cache = None
        self._plans_cache_with_ignored = None
        self._plans_cache_time = 0

    def _scan_all_plans(self, include_ignored: bool = False) -> List[PlanFileResponse]:
        """실제 파일시스템 스캔 (캐시 미스 시 호출)"""
        seen: set[str] = set()
        results: List[PlanFileResponse] = []

        for entry in self._registered_paths:
            is_archive = entry.get("type") == "archive"
            # archive 경로는 include_ignored=True 시에만 스캔 (기본 리스트에서 제외)
            if is_archive and not include_ignored:
                continue
            reg_path = entry["path"]
            p = Path(reg_path)
            if not p.exists():
                continue
            if p.is_dir():
                self._scan_plan_dir(
                    p, seen, results, include_ignored,
                    path_type="folder",
                    recursive=is_archive,
                )
            elif p.is_file():
                if str(p) not in seen:
                    seen.add(str(p))
                    status = self.get_plan_status(p)
                    progress = self.get_plan_progress(p)
                    is_ignored = self._is_ignored_plan(p, status, progress)
                    if include_ignored or not is_ignored:
                        try:
                            content = p.read_text(encoding="utf-8")
                            summary = self._extract_summary(content)
                        except Exception:
                            summary = None
                        results.append(
                            PlanFileResponse(
                                path=str(p),
                                filename=p.name,
                                status=status,
                                progress=progress,
                                source=self._resolve_source(p.parent),
                                ignored=is_ignored,
                                path_type="file",
                                summary=summary,
                            )
                        )

        results.sort(key=lambda x: x.filename, reverse=True)
        return results

    def list_plans(self, include_ignored: bool = False) -> List[PlanFileResponse]:
        """
        plan 목록 조회 — 캐시 우선, 미스 시 파일시스템 스캔

        모든 경로를 동등하게 취급 (고정/외부 구분 없음)
        """
        # TTL 만료 시 캐시 무효화 (runner 종료 트리거 없는 경우 fallback)
        if getattr(self, "_plans_cache", None) is not None and time.monotonic() - getattr(self, "_plans_cache_time", 0) > self._PLANS_CACHE_TTL:
            self.invalidate_plans_cache()

        if include_ignored:
            if self._plans_cache_with_ignored is None:
                self._plans_cache_with_ignored = self._scan_all_plans(include_ignored=True)
                self._plans_cache_time = time.monotonic()
            return self._plans_cache_with_ignored
        else:
            if self._plans_cache is None:
                self._plans_cache = self._scan_all_plans(include_ignored=False)
                self._plans_cache_time = time.monotonic()
            return self._plans_cache

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

    def _get_dir_fingerprint(self, plan_dir: Path) -> float:
        """디렉토리 mtime 반환 (캐시 무효화용, 가벼운 단일 stat)"""
        try:
            return plan_dir.stat().st_mtime
        except Exception:
            return 0.0

    def _scan_plan_dir(
        self,
        plan_dir: Path,
        seen: set,
        results: List[PlanFileResponse],
        include_ignored: bool,
        path_type: Optional[str] = None,
        recursive: bool = False,
    ):
        """plan 디렉토리 스캔

        Args:
            plan_dir: 스캔할 디렉토리
            seen: 이미 처리된 경로 집합 (중복 방지)
            results: 결과 목록 (append)
            include_ignored: True이면 무시된 plan도 포함
            path_type: "folder" | None — PlanFileResponse.path_type에 설정할 값
            recursive: True이면 하위 폴더까지 재귀 스캔 (archive 타입에 사용)
        """
        if not plan_dir.exists():
            return

        # archive 디렉토리는 캐시 사용 (파일 변경이 거의 없음)
        if recursive:
            cache_key = str(plan_dir)
            cached = self._archive_cache.get(cache_key)
            if cached:
                cur_mtime = self._get_dir_fingerprint(plan_dir)
                if cached["mtime"] == cur_mtime:
                    # 캐시 히트: seen 업데이트 + 필터링된 결과 추가
                    for item in cached["results"]:
                        if item.path not in seen:
                            seen.add(item.path)
                            if include_ignored or not item.ignored:
                                results.append(item)
                    return

        source = self._resolve_source(plan_dir)
        scanned_items: List[PlanFileResponse] = []

        glob_fn = plan_dir.rglob if recursive else plan_dir.glob
        for plan_file in glob_fn("*.md"):
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

            try:
                content = plan_file.read_text(encoding="utf-8")
                summary = self._extract_summary(content)
            except Exception:
                summary = None

            item = PlanFileResponse(
                path=str(plan_file),
                filename=plan_file.name,
                status=status,
                progress=progress,
                source=source,
                ignored=is_ignored,
                path_type=path_type,
                summary=summary,
            )
            scanned_items.append(item)

            if include_ignored or not is_ignored:
                results.append(item)

        # archive 디렉토리 결과를 캐시에 저장
        if recursive:
            self._archive_cache[str(plan_dir)] = {
                "mtime": self._get_dir_fingerprint(plan_dir),
                "results": scanned_items,
            }

    # 자동 무시 대상 상태 (정확히 일치해야 함)
    _IGNORED_STATUSES = {"보류", "가이드"}
    # 완료 계열 상태 (아카이브 허용 + 목록 숨김)
    _DONE_STATUSES = {"구현완료", "완료", "수정 완료", "배포완료", "수정완료"}
    # plans 캐시 TTL (초) — runner 종료 트리거 없이도 stale 캐시가 자동 갱신됨
    _PLANS_CACHE_TTL = 60

    def _is_ignored_plan(self, path: Path, status: str, progress: Optional[PlanProgressResponse] = None) -> bool:
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
        # 체크박스 완료 여부는 visibility에 영향 주지 않음
        # — /done 또는 수동 아카이브를 통해서만 목록에서 제거됨
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
            # 멀티레벨 체크박스 지원: "- [x]", "  - [x]", "1. - [x]", "1. [x]" 모두 인식
            checkbox_pattern = r"^[ \t]*(?:\d+\.\s+(?:[-*]\s*)?|[-*]+\s*)\[([ x→])\]"
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
            # 가이드/아이디어/개요 문서 유형 감지
            if doc_type and re.search(r'가이드|guide|아이디어|idea|개요|overview|설계|design', doc_type, re.IGNORECASE):
                return "가이드"
            if any(kw in stem for kw in ('-guide', '-overview', '-idea', '-design', '-spec')):
                return "가이드"
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

    @staticmethod
    def _extract_summary(content: str) -> Optional[str]:
        """plan 파일에서 요약 텍스트를 추출한다.

        우선순위:
        1. `> 요약: {텍스트}` 헤더 블록쿼트
        2. `## 개요` 섹션 첫 단락 (코드블럭 제외)
        3. `## 요약` 섹션 (구버전 하위 호환)
        """
        lines = content.split("\n")

        # 1. `> 요약:` 블록쿼트 탐색
        for line in lines:
            m = re.match(r'^>\s*요약:\s*(.+)', line)
            if m:
                text = m.group(1).strip()
                if text:
                    return text

        # 2. `## 개요` 섹션 첫 단락
        in_개요 = False
        in_codeblock = False
        collected: List[str] = []
        for line in lines:
            if re.match(r'^##\s+개요', line):
                in_개요 = True
                continue
            if in_개요:
                if re.match(r'^##\s+', line):
                    break
                if line.strip().startswith('```'):
                    in_codeblock = not in_codeblock
                    continue
                if in_codeblock:
                    continue
                # 빈 줄이 나오고 이미 내용이 있으면 첫 단락 종료
                if not line.strip() and collected:
                    break
                if line.strip():
                    collected.append(line.strip())
        text = " ".join(collected).strip()
        if text:
            return text

        # 3. `## 요약` (구버전 하위 호환)
        in_section = False
        collected = []
        for line in lines:
            if re.match(r'^##\s+요약', line):
                in_section = True
                continue
            if in_section:
                if re.match(r'^##\s+', line):
                    break
                collected.append(line)
        text = "\n".join(collected).strip()
        return text if text else None

    def parse_plan_items(self, path: Path) -> PlanDetailResponse:
        """plan 파일을 Phase별 항목으로 파싱"""
        # _todo 파일이 있으면 우선 사용
        todo_file = self._find_todo_file(path)
        parse_path = todo_file if todo_file else path

        content = parse_path.read_text(encoding="utf-8", errors="ignore")
        # 요약: todo 파일 우선, 없으면 원본 plan에서 fallback
        summary = self._extract_summary(content)
        if summary is None and todo_file is not None:
            orig_content = path.read_text(encoding="utf-8", errors="ignore")
            summary = self._extract_summary(orig_content)
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
            summary=summary,
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
        # 멀티레벨 체크박스 지원: "- [ ]", "  - [ ]", "1. - [ ]" 모두 인식
        matches = re.findall(r'^[ \t]*(?:\d+\.\s+)?[-*]\s*\[ \]\s*(.+)$', cleaned, re.MULTILINE)
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
    def _validate_done_preconditions(file_path: str, content: str) -> list:
        """done 처리 전 사전 검증. 실패 사유 리스트 반환 (빈 리스트 = 통과)"""
        errors = []
        # branch/worktree 필드 잔존
        if re.search(r">\s*(branch|worktree):", content[:2000]):
            errors.append("branch/worktree 필드 잔존 — /merge-test 먼저 실행 필요")
        # fix plan 판정
        name = Path(file_path).name
        is_fix = "_fix-" in name or "_fix_" in name
        if not is_fix:
            for line in content.split("\n")[:5]:
                if line.startswith("# fix") and len(line) > 5 and line[5] in (":", "-", " "):
                    is_fix = True
                    break
            if not is_fix and re.search(r">\s*유형:\s*fix", content[:1000]):
                is_fix = True
        if is_fix:
            has_pr = "Phase R" in content or "재발 경로 분석" in content
            if not has_pr:
                errors.append("fix plan Phase R 섹션 필수 — /implement에서 Phase R 먼저 실행")
            elif has_pr:
                m = re.search(r"### Phase R.*?(?=\n### |\Z)", content, re.DOTALL)
                if m:
                    section = re.sub(r"```.*?```", "", m.group(0), flags=re.DOTALL)
                    if "미방어" in section:
                        errors.append("Phase R에 미방어 경로 잔존 — 모든 경로 방어 완료 필요")
        return errors

    @staticmethod
    def _update_plan_headers(content: str, total: int) -> str:
        """상태→구현완료, 진행률→100%, [→ID]→[x] 치환, 푸터 갱신"""
        content = re.sub(r'^(>\s*상태:\s*).*$', r'\1구현완료', content, flags=re.MULTILINE)
        # branch/worktree 헤더 제거 — 잔존 시 /done 스킬 2.5단계에서 차단됨 (post-merge 이후이므로 삭제 안전)
        content = re.sub(r'^>\s*(branch|worktree):.*\n?', '', content, flags=re.MULTILINE)
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

    async def _archive_plan(self, plan_path: str, content: str) -> tuple[Path, Optional[Path]]:
        """완료일 헤더 삽입 후 git mv로 archive 디렉토리로 이동.

        Returns:
            (archive_path, todo_archive_path) — todo_archive_path는 companion _todo.md가 없으면 None
        """
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

        # 4. companion _todo.md 아카이브 처리
        todo_archive_path: Optional[Path] = None
        todo_file = self._find_todo_file(p)
        if todo_file and todo_file.exists():
            todo_archive_path = archive_dir / todo_file.name
            todo_mv_proc = await asyncio.create_subprocess_exec(
                "git", "mv", str(todo_file), str(todo_archive_path),
                cwd=str(todo_file.parent),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await todo_mv_proc.communicate()
            if todo_mv_proc.returncode != 0:
                # fallback: 파일시스템 이동
                todo_archive_path.write_text(todo_file.read_text(encoding="utf-8"), encoding="utf-8")
                todo_file.unlink()

        return archive_path, todo_archive_path

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

            # 0. 사전 검증 (구현완료 설정 전 게이트)
            precondition_errors = self._validate_done_preconditions(plan_path, content)
            if precondition_errors:
                raise ValueError(f"done 사전 검증 실패: {'; '.join(precondition_errors)}")

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
            archive_path, todo_archive_path = await self._archive_plan(plan_path, updated_content)

            # 4. TODO.md / DONE.md 업데이트
            if project_dir:
                self._update_todo_done(project_dir, title)
                done_path = project_dir / "docs" / "DONE.md"
                self._archive_done_if_needed(done_path)

            # 5. git commit
            files_to_commit: List[Path] = [archive_path]
            if todo_archive_path:
                files_to_commit.append(todo_archive_path)
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
                    svc.update_status(plan_path, "completed")
                    svc.mark_archived(plan_path, str(archive_path))
                    db.commit()
            except Exception as db_err:
                logger.warning(f"plan_record DB 기록 실패 (무시): {db_err}")

            # Redis pub/sub 트리거: plan:archived 채널에 아카이브 경로 발행
            try:
                _publish_log("plan", f"archived: {archive_path}")
                r = _get_redis()
                if r:
                    r.publish("plan:archived", str(archive_path))
            except Exception as redis_err:
                logger.debug(f"plan:archived publish 실패 (무시): {redis_err}")

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

        # 체크박스가 없는 문서(분석서, 보고서 등): 아카이브 허용
        if not detail.phases or all(len(p.items) == 0 for p in detail.phases):
            progress = self.get_plan_progress(plan_path)
            if progress.total == 0:
                return VerifyResult(total=0, verified=0, unverified_items=[], percent=100.0, can_done=True)

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

    def _check_branch_exists(self, branch: str) -> bool:
        """git branch가 존재하는지 확인. subprocess 실패 시 False (안전 기본값)"""
        try:
            result = subprocess.run(
                ["git", "branch", "--list", branch],
                capture_output=True, text=True, timeout=5
            )
            return bool(result.stdout.strip())
        except Exception:
            return False

    def _check_worktree_exists(self, worktree_path: str) -> bool:
        """git worktree가 존재하는지 확인. subprocess 실패 시 False (안전 기본값)"""
        try:
            result = subprocess.run(
                ["git", "worktree", "list", "--porcelain"],
                capture_output=True, text=True, timeout=5
            )
            return worktree_path in result.stdout
        except Exception:
            return False

    def _can_done(self, plan: PlanFileResponse) -> bool:
        """plan이 done 처리 가능한지 판단 — 체크박스 전체 완료 OR 상태 헤더 완료 계열 OR 체크박스 없음"""
        if "archive" in plan.path:
            return False

        # worktree/branch 존재 여부 확인 — 살아있으면 done 불가
        try:
            p = Path(plan.path)
            if p.exists():
                top20 = ""
                with open(p, "r", encoding="utf-8", errors="ignore") as f:
                    for i, line in enumerate(f):
                        if i >= 20:
                            break
                        top20 += line
                branch_match = re.search(r'^>\s*branch:\s*(.+)', top20, re.MULTILINE)
                if branch_match and self._check_branch_exists(branch_match.group(1).strip()):
                    return False
                worktree_match = re.search(r'^>\s*worktree:\s*(.+)', top20, re.MULTILINE)
                if worktree_match and self._check_worktree_exists(worktree_match.group(1).strip()):
                    return False
        except Exception:
            pass  # 파일 읽기 실패 시 기존 로직으로 진행

        progress = plan.progress
        if progress is None:
            progress = self.get_plan_progress(Path(plan.path))
        # 가이드 문서는 done 불가
        if plan.status == "가이드":
            return False
        # 체크박스 없는 문서(분석서, 보고서 등): 아카이브 허용
        if progress.total == 0:
            return True
        if progress.total > 0 and progress.done == progress.total:
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
            self.invalidate_plans_cache()
        return found

    # ========== 동기화 ==========

    def sync_plans(self) -> dict:
        """plan 동기화 — 이전 상태와 비교하여 변경 요약 반환"""
        # 이전 상태 스냅샷 (활성 plan만 — archive는 sync 대상 아님)
        old_plans = {p.path: p for p in self.list_plans()}
        old_keys = set(old_plans.keys())

        # 디스크에서 다시 스캔 (캐시 무효화)
        self._load_registered_paths()
        self.invalidate_plans_cache()
        new_plans_list = self.list_plans()
        new_plans = {p.path: p for p in new_plans_list}
        new_keys = set(new_plans.keys())

        added = len(new_keys - old_keys)
        removed = len(old_keys - new_keys)

        updated = 0
        for key in old_keys & new_keys:
            old_p = old_plans[key]
            new_p = new_plans[key]
            old_done = old_p.progress.done if old_p.progress else 0
            old_total = old_p.progress.total if old_p.progress else 0
            new_done = new_p.progress.done if new_p.progress else 0
            new_total = new_p.progress.total if new_p.progress else 0
            if (old_p.status != new_p.status
                    or old_done != new_done
                    or old_total != new_total):
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
                glob_fn = p.rglob if path_type == "archive" else p.glob
                plan_count = sum(
                    1 for f in glob_fn("*.md")
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

    def update_plan_status(self, path: str, new_status: str) -> str:
        """plan 파일의 상태 필드를 업데이트한다.

        - 파일 상단 20줄에서 `> 상태: ...` 라인을 찾아 교체
        - 라인이 없으면 첫 번째 `#` 제목 다음 줄에 삽입
        - 허용 상태: 초안, 검토대기, 검토완료, 구현중, 구현완료, 보류
        """
        ALLOWED_STATUSES = ["초안", "검토대기", "검토완료", "구현중", "테스트중", "머지대기", "구현완료", "보류"]
        if new_status not in ALLOWED_STATUSES:
            raise ValueError(
                f"허용되지 않은 상태: '{new_status}'. 허용 목록: {ALLOWED_STATUSES}"
            )

        file_path = Path(path)
        if not file_path.exists():
            raise FileNotFoundError(f"파일을 찾을 수 없습니다: {path}")

        content = file_path.read_text(encoding="utf-8")
        lines = content.splitlines(keepends=True)

        import re

        status_pattern = re.compile(r"^> 상태: .+")

        # 상단 20줄에서 `> 상태:` 라인 교체
        found = False
        for i, line in enumerate(lines[:20]):
            if status_pattern.match(line.rstrip("\n\r")):
                lines[i] = f"> 상태: {new_status}\n"
                found = True
                break

        if not found:
            # `> 상태:` 라인 없음 → 첫 번째 `#` 제목 다음 줄에 삽입
            for i, line in enumerate(lines):
                if line.startswith("#"):
                    lines.insert(i + 1, f"> 상태: {new_status}\n")
                    found = True
                    break

        if not found:
            # 제목도 없으면 파일 맨 앞에 삽입
            lines.insert(0, f"> 상태: {new_status}\n")

        file_path.write_text("".join(lines), encoding="utf-8")
        self.invalidate_plans_cache()
        return new_status

    def _insert_summary_to_plan(self, path: Path, summary_text: str) -> None:
        """plan 파일의 헤더 블록쿼트에 `> 요약:` 줄을 삽입(또는 교체)한다."""
        content = path.read_text(encoding="utf-8")
        lines = content.split("\n")

        # 기존 `> 요약:` 줄 교체
        for i, line in enumerate(lines):
            if re.match(r'^>\s*요약:', line):
                lines[i] = f"> 요약: {summary_text}"
                path.write_text("\n".join(lines), encoding="utf-8")
                self.invalidate_plans_cache()
                return

        # 없으면 첫 번째 블록쿼트 줄 뒤에 삽입 (없으면 h1 제목 다음에 삽입)
        insert_idx = None
        for i, line in enumerate(lines):
            if line.startswith(">"):
                insert_idx = i + 1
                break
        if insert_idx is None:
            for i, line in enumerate(lines):
                if line.startswith("# "):
                    insert_idx = i + 1
                    break
        if insert_idx is None:
            insert_idx = 0
        lines.insert(insert_idx, f"> 요약: {summary_text}")
        path.write_text("\n".join(lines), encoding="utf-8")
        self.invalidate_plans_cache()

    async def generate_summary(self, path: Path, db) -> int:
        """plan 파일 내용을 LLM으로 요약하여 `> 요약:` 헤더에 삽입한다.

        Returns:
            LLMRequest.id (request_id)
        """
        from app.modules.claude_worker.services.llm_service import LLMService

        content = path.read_text(encoding="utf-8")
        prompt = (
            "다음 plan 문서를 읽고 1-2 문장으로 핵심 목적을 한국어로 요약해줘. "
            "코드블록 없이 일반 텍스트만 출력해.\n\n"
            f"{content[:3000]}"
        )

        llm_svc = LLMService(db)
        request = llm_svc.enqueue(
            caller_type="dev_runner",
            caller_id=str(path),
            prompt=prompt,
            requested_by="api",
            request_source="plan_summary",
            provider="claude",
            model="",
            queue_name="utility",
        )
        db.commit()

        # 백그라운드에서 완료 후 plan 파일에 요약 삽입
        plan_path = path
        request_id = request.id
        plan_svc = self

        async def _write_back():
            import asyncio
            from app.database import SessionLocal
            for _ in range(60):  # 최대 5분 대기 (5초 x 60)
                await asyncio.sleep(5)
                with SessionLocal() as bg_db:
                    from app.modules.claude_worker.models.llm_request import LLMRequest
                    req = bg_db.query(LLMRequest).filter(LLMRequest.id == request_id).first()
                    if req and req.status == "completed" and req.raw_response:
                        summary_text = req.raw_response.strip()
                        if summary_text:
                            plan_svc._insert_summary_to_plan(plan_path, summary_text)
                        return
                    if req and req.status in ("failed", "cancelled"):
                        return

        import asyncio
        asyncio.create_task(_write_back())

        return request_id


# 싱글톤 인스턴스
plan_service = PlanService()

__all__ = ['plan_service', 'PlanService']
