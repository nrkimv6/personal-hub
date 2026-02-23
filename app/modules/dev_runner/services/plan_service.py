"""plan 문서 관리 서비스"""

import asyncio
import json
import logging
import re
import redis
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
        self._registered_paths: List[str] = []
        self._ignored_plans: List[str] = []
        self._migrate_to_registered_paths()
        self._load_registered_paths()
        self._load_ignored_plans()

    # ========== 경로 저장/로드 ==========

    def _migrate_to_registered_paths(self):
        """external_plans.json → registered_paths.json 마이그레이션 (1회성)"""
        reg_path = config.REGISTERED_PATHS_FILE
        if reg_path.exists():
            return  # 이미 마이그레이션 완료

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

        # 저장
        if paths:
            reg_path.parent.mkdir(parents=True, exist_ok=True)
            reg_path.write_text(json.dumps(paths, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info(f"[마이그레이션] registered_paths.json 생성 완료 ({len(paths)}개)")

    def _load_registered_paths(self):
        """등록된 경로 목록 로드 (JSON 파일)"""
        path = config.REGISTERED_PATHS_FILE
        if path.exists():
            try:
                self._registered_paths = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                self._registered_paths = []

    def _save_registered_paths(self):
        """등록된 경로 목록 저장"""
        path = config.REGISTERED_PATHS_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self._registered_paths, ensure_ascii=False, indent=2), encoding="utf-8")

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

    def add_path(self, plan_path: str) -> bool:
        """등록 경로 추가 (영구 저장)"""
        resolved = str(Path(plan_path).resolve())
        if resolved not in self._registered_paths:
            self._registered_paths.append(resolved)
            self._save_registered_paths()
            return True
        return False

    def remove_path(self, plan_path: str) -> bool:
        """등록 경로 제거"""
        resolved = str(Path(plan_path).resolve())
        if resolved in self._registered_paths:
            self._registered_paths.remove(resolved)
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

        for reg_path in self._registered_paths:
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
    _IGNORED_STATUSES = {"완료", "보류"}

    def _is_ignored_plan(self, path: Path, status: str, progress: PlanProgressResponse) -> bool:
        """plan이 무시 대상인지 판단"""
        # 수동 무시 목록
        if str(path.resolve()) in self._ignored_plans:
            return True
        # 완료 상태 (정확히 일치하는 경우만)
        if status in self._IGNORED_STATUSES:
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
                    type_match = re.match(r">\s*유형:\s*(.+)", line)
                    if type_match:
                        doc_type = self._strip_markdown_inline(type_match.group(1))
            # 상태 라인이 없고, 보고서 유형이면 완료로 간주
            if doc_type and re.search(r'보고서|report', doc_type, re.IGNORECASE):
                return "완료"
            # 파일명에 -report 포함 시 완료로 간주
            if '-report' in path.stem.lower():
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

            # 대시 체크박스 (하위): - [ ] or - [x]
            dash_match = re.match(r'^\s+-\s*\[([ x→])\]\s*(.*)', line)
            if dash_match and current_parent is not None:
                text = dash_match.group(2).strip()
                fp = file_path_pattern.search(text)
                child = PlanItemResponse(
                    level=1,
                    text=text,
                    checked=dash_match.group(1) == 'x',
                    file_path=fp.group(1) if fp else None,
                )
                current_parent.children.append(child)

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

    # ========== done 처리 ==========

    AUTO_DONE_SCRIPT = Path("D:/work/project/service/wtools/common/tools/auto-done.ps1")

    async def run_done(self, plan_path: str) -> dict:
        """auto-done.ps1 실행하여 plan 완료 처리 (아카이브, TODO→DONE, 커밋)"""
        if not self.AUTO_DONE_SCRIPT.exists():
            return {"success": False, "message": f"auto-done.ps1 not found: {self.AUTO_DONE_SCRIPT}", "output": None,
                    "remaining_tasks": 0, "total_tasks": 0, "plan_status": ""}

        path = Path(plan_path)
        if not path.exists():
            return {"success": False, "message": f"Plan file not found: {plan_path}", "output": None,
                    "remaining_tasks": 0, "total_tasks": 0, "plan_status": ""}

        # done 실행 전 현재 progress/status 캡처
        pre_progress = self.get_plan_progress(path)
        pre_status = self.get_plan_status(path)

        try:
            proc = await asyncio.create_subprocess_exec(
                "powershell.exe", "-ExecutionPolicy", "Bypass",
                "-File", str(self.AUTO_DONE_SCRIPT),
                "-PlanFile", plan_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
            output = stdout.decode("utf-8", errors="replace") if stdout else ""

            if proc.returncode == 0:
                self.sync_plans()
                return {
                    "success": True, "message": "완료 처리 성공", "output": output,
                    "remaining_tasks": pre_progress.total - pre_progress.done,
                    "total_tasks": pre_progress.total,
                    "plan_status": pre_status,
                }
            else:
                return {
                    "success": False, "message": f"auto-done.ps1 실패 (exit={proc.returncode})", "output": output,
                    "remaining_tasks": pre_progress.total - pre_progress.done,
                    "total_tasks": pre_progress.total,
                    "plan_status": pre_status,
                }
        except asyncio.TimeoutError:
            return {"success": False, "message": "auto-done.ps1 타임아웃 (120초)", "output": None,
                    "remaining_tasks": 0, "total_tasks": 0, "plan_status": ""}
        except Exception as e:
            logger.error(f"run_done 실패: {e}")
            return {"success": False, "message": str(e), "output": None,
                    "remaining_tasks": 0, "total_tasks": 0, "plan_status": ""}

    # ========== 일괄 완료 ==========

    def _can_done(self, plan: PlanFileResponse) -> bool:
        """plan이 done 처리 가능한지 판단"""
        if "archive" in plan.path:
            return False
        if plan.progress.total > 0 and plan.progress.done == plan.progress.total:
            return True
        if plan.status in ("구현완료", "완료"):
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

        # PLAN_LIST: 쉼표 구분 파일명 (숫자 아님!)
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
                _publish_log("BATCH", f"PLAN_DONE {plan.filename}")
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

        for reg_path in self._registered_paths:
            p = Path(reg_path)
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
        for reg_path in self._registered_paths:
            p = Path(reg_path)
            if not p.is_dir():
                continue
            resolved = str(p.resolve())
            if not resolved.startswith(wtools_prefix):
                extra_dirs.append(resolved)
        return extra_dirs

    # ========== 등록 경로 관리 ==========

    def list_registered_paths(self) -> List[RegisteredPathResponse]:
        """등록된 경로 목록 조회 (타입 + plan_count 포함)"""
        result = []
        for reg_path in self._registered_paths:
            p = Path(reg_path)
            if p.is_dir():
                plan_count = sum(
                    1 for f in p.glob("*.md")
                    if f.stem.endswith("_todo")
                    or not (f.parent / (f.stem + "_todo.md")).exists()
                ) if p.exists() else 0
                result.append(RegisteredPathResponse(path=reg_path, type="folder", plan_count=plan_count))
            else:
                result.append(RegisteredPathResponse(path=reg_path, type="file", plan_count=1 if p.exists() else 0))
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
