"""
폴더 트리 스캔 워커

- 재귀적으로 폴더 탐색
- 이미지 파일 필터링 (jpg/png/gif/bmp/webp/heic/tiff)
- DB에 파일 정보 저장
- 진행 상태 콜백
"""

import hashlib
from pathlib import Path
from typing import Callable, Optional
from sqlalchemy import text
from sqlalchemy.orm import Session


class FolderScanner:
    """폴더 트리 스캔 워커"""

    def __init__(self, db: Session, settings):
        self.db = db
        self.settings = settings
        self.image_extensions = settings.IMAGE_EXTENSIONS

        # 통계
        self.total_folders = 0
        self.scanned_folders = 0
        self.total_files = 0
        self.scanned_files = 0

    async def scan_folders(
        self,
        root_folders: list[str],
        on_progress: Optional[Callable] = None,
    ):
        """
        폴더 트리 스캔 메인 함수

        Args:
            root_folders: 스캔 대상 루트 폴더 목록
            on_progress: 진행 상태 콜백 함수
        """
        # 1단계: 폴더 트리 수집
        all_folders = []
        for root in root_folders:
            root_path = Path(root)
            if not root_path.exists():
                print(f"[경고] 폴더가 존재하지 않음: {root}")
                continue

            folders = self._collect_folders(root_path)
            all_folders.extend(folders)

        self.total_folders = len(all_folders)
        print(f"[스캔] 발견된 폴더: {self.total_folders}개")

        # 2단계: 각 폴더에서 이미지 파일 수집
        for folder_path in all_folders:
            await self._scan_folder_files(folder_path)
            self.scanned_folders += 1

            # 진행 상태 콜백
            if on_progress:
                on_progress(
                    total_folders=self.total_folders,
                    scanned_folders=self.scanned_folders,
                    total_files=self.total_files,
                    scanned_files=self.scanned_files,
                    current_folder=str(folder_path),
                )

    def _collect_folders(self, root_path: Path) -> list[Path]:
        """
        재귀적으로 모든 폴더 수집

        Returns:
            폴더 경로 리스트
        """
        folders = [root_path]

        try:
            for item in root_path.iterdir():
                if item.is_dir() and not item.name.startswith('.'):
                    # 재귀 호출
                    sub_folders = self._collect_folders(item)
                    folders.extend(sub_folders)
        except PermissionError:
            print(f"[경고] 접근 권한 없음: {root_path}")
        except Exception as e:
            print(f"[경고] 폴더 읽기 오류: {root_path} - {e}")

        return folders

    async def _scan_folder_files(self, folder_path: Path):
        """
        폴더 내 이미지 파일 스캔 및 DB 저장

        Args:
            folder_path: 스캔할 폴더 경로
        """
        try:
            # 이미지 파일 필터링
            image_files = [
                f for f in folder_path.iterdir()
                if f.is_file() and f.suffix.lower() in self.image_extensions
            ]

            if not image_files:
                return  # 이미지 파일 없으면 스킵

            # folder_mappings 테이블에 폴더 정보 저장
            folder_id = self._save_folder_mapping(folder_path, len(image_files))

            # 각 파일 정보 저장
            for file_path in image_files:
                await self._save_file_info(file_path, folder_id)
                self.scanned_files += 1

            self.total_files += len(image_files)

        except PermissionError:
            print(f"[경고] 접근 권한 없음: {folder_path}")
        except Exception as e:
            print(f"[오류] 파일 스캔 실패: {folder_path} - {e}")

    def _scan_folder_files_sync(self, folder_path: Path):
        """
        _scan_folder_files의 동기 버전 (to_thread에서 호출용)
        이벤트 루프 블로킹 방지를 위해 스레드 풀에서 실행
        """
        try:
            image_files = [
                f for f in folder_path.iterdir()
                if f.is_file() and f.suffix.lower() in self.image_extensions
            ]

            if not image_files:
                return

            folder_id = self._save_folder_mapping(folder_path, len(image_files))

            for file_path in image_files:
                self._save_file_info_sync(file_path, folder_id)
                self.scanned_files += 1

            self.total_files += len(image_files)

        except PermissionError:
            print(f"[경고] 접근 권한 없음: {folder_path}")
        except Exception as e:
            print(f"[오류] 파일 스캔 실패: {folder_path} - {e}")

    def _save_folder_mapping(self, folder_path: Path, file_count: int) -> int:
        """
        folder_mappings 테이블에 폴더 정보 저장

        Returns:
            folder_id
        """
        folder_str = str(folder_path)

        # 기존 레코드 확인
        result = self.db.execute(
            text("SELECT id FROM folder_mappings WHERE folder_path = :path"),
            {"path": folder_str}
        ).fetchone()

        if result:
            # 기존 레코드 업데이트 (파일 수)
            folder_id = result.id
            self.db.execute(
                text("UPDATE folder_mappings SET file_count = :count WHERE id = :id"),
                {"count": file_count, "id": folder_id}
            )
        else:
            # 신규 삽입
            self.db.execute(
                text("""
                    INSERT INTO folder_mappings (folder_path, file_count, folder_status)
                    VALUES (:path, :count, 'unknown')
                """),
                {"path": folder_str, "count": file_count}
            )
            self.db.commit()

            # 방금 삽입된 ID 조회
            result = self.db.execute(
                text("SELECT id FROM folder_mappings WHERE folder_path = :path"),
                {"path": folder_str}
            ).fetchone()
            folder_id = result.id

        self.db.commit()
        return folder_id

    async def _save_file_info(self, file_path: Path, folder_id: int):
        """
        file_classifications 테이블에 파일 정보 저장

        Args:
            file_path: 파일 경로
            folder_id: 소속 폴더 ID
        """
        self._save_file_info_sync(file_path, folder_id)

    def _save_file_info_sync(self, file_path: Path, folder_id: int):
        """
        _save_file_info의 동기 버전 (to_thread에서 호출용)
        """
        file_str = str(file_path)

        # 중복 체크
        exists = self.db.execute(
            text("SELECT 1 FROM file_classifications WHERE file_path = :path"),
            {"path": file_str}
        ).fetchone()

        if exists:
            return  # 이미 존재하면 스킵

        # 파일 메타데이터 수집
        try:
            file_stat = file_path.stat()
            file_size = file_stat.st_size
            file_modified = file_stat.st_mtime

            # SHA256 해시 계산
            file_hash = self._compute_file_hash(file_path)

            # DB 삽입
            self.db.execute(
                text("""
                    INSERT INTO file_classifications (
                        file_path, file_hash, file_size, file_modified_at,
                        source_folder_id, status
                    ) VALUES (
                        :path, :hash, :size, datetime(:modified, 'unixepoch'),
                        :folder_id, 'pending'
                    )
                """),
                {
                    "path": file_str,
                    "hash": file_hash,
                    "size": file_size,
                    "modified": file_modified,
                    "folder_id": folder_id,
                }
            )
            self.db.commit()

        except Exception as e:
            print(f"[오류] 파일 정보 저장 실패: {file_path} - {e}")

    def _compute_file_hash(self, file_path: Path) -> str:
        """
        파일의 SHA256 해시 계산

        Returns:
            해시 문자열 (hex)
        """
        sha256 = hashlib.sha256()

        try:
            with open(file_path, 'rb') as f:
                while True:
                    chunk = f.read(8192)
                    if not chunk:
                        break
                    sha256.update(chunk)

            return sha256.hexdigest()

        except Exception as e:
            print(f"[오류] 해시 계산 실패: {file_path} - {e}")
            return ""
