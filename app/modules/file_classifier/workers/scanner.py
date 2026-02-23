"""
파일 스캐너

폴더 재귀 스캔 + 확장자별 file_group 자동 분류 + fc_files INSERT
"""

import os
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import settings
from .task_progress import TaskProgressManager


# 확장자 → file_group 매핑
FILE_GROUP_MAP: dict[str, str] = {}

_GROUP_EXTENSIONS = {
    "music": {".mp3", ".flac", ".ogg", ".wav", ".wma", ".aac", ".m4a", ".mid", ".midi"},
    "archive": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2"},
    "document": {
        ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
        ".hwp", ".txt", ".csv", ".json", ".xml", ".md", ".rtf"
    },
    "installer": {".exe", ".msi", ".bat", ".ps1", ".cmd"},
    "game": {".dtx", ".gda", ".g2d", ".bms", ".bme", ".bml"},
}

# 역방향 매핑 빌드
for _group, _exts in _GROUP_EXTENSIONS.items():
    for _ext in _exts:
        FILE_GROUP_MAP[_ext] = _group


def get_file_group(extension: str) -> str:
    """확장자로 file_group 반환 (없으면 'misc')"""
    return FILE_GROUP_MAP.get(extension.lower(), "misc")


class FileScanner:
    """폴더 재귀 스캔 + file_group 분류 + DB 저장"""

    def __init__(self, db: Session):
        self.db = db
        self._stop_flag = False

    def stop(self):
        """스캔 중지 요청"""
        self._stop_flag = True

    def scan(
        self,
        root_folders: list[str],
        task_id: Optional[int] = None,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> dict:
        """
        폴더 목록 스캔

        Args:
            root_folders: 스캔할 루트 폴더 경로 목록
            task_id: fc_task_progress 레코드 ID (진행률 업데이트용)
            progress_callback: (processed, total, current_path) 콜백

        Returns:
            {"total": int, "inserted": int, "skipped": int, "errors": int}
        """
        self._stop_flag = False
        stats = {"total": 0, "inserted": 0, "skipped": 0, "errors": 0}
        progress_mgr = TaskProgressManager(self.db) if task_id else None

        exclude_names = set(settings.EXCLUDE_FOLDERS)
        max_files = settings.MAX_FILES_PER_SCAN

        # 1단계: 파일 목록 수집 (진행률 계산용)
        all_files: list[Path] = []
        for root_folder in root_folders:
            root_path = Path(root_folder)
            if not root_path.exists():
                print(f"[경고] 존재하지 않는 폴더 스킵: {root_folder}")
                continue
            for file_path in self._walk_files(root_path, exclude_names):
                all_files.append(file_path)
                if len(all_files) >= max_files:
                    print(f"[정보] 최대 스캔 수({max_files}) 도달, 조기 종료")
                    break
            if len(all_files) >= max_files:
                break

        total = len(all_files)
        stats["total"] = total

        if progress_mgr and task_id:
            progress_mgr.update_progress(task_id, 0, f"총 {total}개 파일 발견")

        # 2단계: DB 저장
        batch: list[dict] = []
        for i, file_path in enumerate(all_files):
            if self._stop_flag:
                print("[정보] 스캔 중지 요청 수신")
                break

            try:
                row = self._build_row(file_path)
                batch.append(row)
                stats["inserted"] += 1
            except Exception as e:
                stats["errors"] += 1
                print(f"[경고] 파일 처리 오류 ({file_path}): {e}")

            # 배치 커밋 (100개 단위)
            if len(batch) >= 100:
                self._upsert_batch(batch)
                batch = []

            # 진행률 업데이트 (50개마다)
            if (i + 1) % 50 == 0:
                if progress_mgr and task_id:
                    progress_mgr.update_progress(task_id, i + 1, str(file_path))
                if progress_callback:
                    progress_callback(i + 1, total, str(file_path))

        # 나머지 배치 커밋
        if batch:
            self._upsert_batch(batch)

        return stats

    def _walk_files(self, root: Path, exclude_names: set[str]):
        """폴더 재귀 탐색 (제외 폴더 스킵)"""
        try:
            for entry in os.scandir(root):
                if self._stop_flag:
                    return
                if entry.is_dir(follow_symlinks=False):
                    if entry.name not in exclude_names:
                        yield from self._walk_files(Path(entry.path), exclude_names)
                elif entry.is_file(follow_symlinks=False):
                    yield Path(entry.path)
        except PermissionError:
            pass  # 접근 권한 없는 폴더 스킵

    def _build_row(self, file_path: Path) -> dict:
        """파일 정보 → DB 행 딕셔너리 생성"""
        stat = file_path.stat()
        extension = file_path.suffix.lower()
        file_group = get_file_group(extension)
        modified_at = datetime.fromtimestamp(stat.st_mtime).isoformat()

        return {
            "file_path": str(file_path),
            "file_name": file_path.name,
            "extension": extension,
            "file_size": stat.st_size,
            "file_modified_at": modified_at,
            "file_group": file_group,
        }

    def _upsert_batch(self, batch: list[dict]):
        """배치 UPSERT (이미 존재하면 스킵)"""
        for row in batch:
            try:
                self.db.execute(
                    text("""
                        INSERT OR IGNORE INTO fc_files
                            (file_path, file_name, extension, file_size, file_modified_at, file_group)
                        VALUES
                            (:file_path, :file_name, :extension, :file_size, :file_modified_at, :file_group)
                    """),
                    row
                )
            except Exception as e:
                print(f"[경고] DB INSERT 오류: {e}")
        self.db.commit()
