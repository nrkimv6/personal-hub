"""
폴더 자동 분류 워커

폴더명 및 구조를 분석하여 자동으로 상태를 판정:
- clear: 폴더명에 의미가 명확함
- unclear: 폴더명이 불명확함 (새 폴더, 숫자만 등)
- flat: 파일만 많고 서브폴더가 없음 (500개 이상)
- nested: 깊은 중첩 구조
"""

import re
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import text


class FolderClassifier:
    """폴더 자동 분류기"""

    # 명확한 폴더명 패턴 (의미 있는 단어가 포함됨)
    CLEAR_PATTERNS = [
        r"여행|travel|trip",
        r"가족|family",
        r"친구|friend",
        r"음식|food|맛집|restaurant",
        r"풍경|경치|landscape|scenery",
        r"야경|night.*view",
        r"일상|daily|life",
        r"자연|nature",
        r"건물|building|architecture",
        r"동물|animal|pet",
        r"꽃|flower|plant",
        r"사람|people|person|portrait",
        r"스크린샷|screenshot|캡처|capture",
        r"졸업|graduation",
        r"결혼|wedding",
        r"생일|birthday",
        r"축제|festival|event",
        r"공연|concert|performance",
        r"전시|exhibition|museum",
        r"회의|meeting|conference",
        r"프로젝트|project|work",
        r"영수증|receipt|invoice",
        r"증명|identification|id|license|passport",
        r"학교|school|university|college",
        r"카페|cafe|coffee",
    ]

    # 불명확한 폴더명 패턴
    UNCLEAR_PATTERNS = [
        r"^새\s*폴더\s*\d*$",  # 새 폴더, 새 폴더 (2)
        r"^new\s*folder\s*\d*$",
        r"^\d+$",  # 숫자만
        r"^folder\s*\d*$",
        r"^temp\s*\d*$",
        r"^backup\s*\d*$",
        r"^기타\s*\d*$",
        r"^misc\s*\d*$",
        r"^untitled\s*\d*$",
        r"^noname\s*\d*$",
    ]

    # 날짜만 있는 폴더명 패턴 (불명확으로 처리)
    DATE_ONLY_PATTERNS = [
        r"^\d{8}$",  # 20230415
        r"^\d{4}-\d{2}-\d{2}$",  # 2023-04-15
        r"^\d{4}\.\d{2}\.\d{2}$",  # 2023.04.15
        r"^\d{4}년\s*\d{1,2}월\s*\d{1,2}일$",  # 2023년 4월 15일
    ]

    def __init__(self, db: Session):
        self.db = db

    def classify_folder(self, folder_path: str, file_count: int, subfolders: list[str]) -> str:
        """
        폴더 상태 자동 판정

        Args:
            folder_path: 폴더 경로
            file_count: 폴더 내 파일 수
            subfolders: 서브폴더 목록

        Returns:
            folder_status: clear/unclear/flat/nested
        """
        folder_name = Path(folder_path).name.lower()

        # 1. 플랫 폴더 검사 (우선순위 높음)
        if file_count >= 500 and len(subfolders) == 0:
            return "flat"

        # 2. 깊은 중첩 검사
        depth = len(Path(folder_path).parts)
        if depth > 5 and len(subfolders) > 0:
            return "nested"

        # 3. 불명확 패턴 검사
        for pattern in self.UNCLEAR_PATTERNS:
            if re.search(pattern, folder_name, re.IGNORECASE):
                return "unclear"

        # 4. 날짜만 있는 패턴 검사
        for pattern in self.DATE_ONLY_PATTERNS:
            if re.match(pattern, folder_name):
                return "unclear"

        # 5. 명확 패턴 검사
        for pattern in self.CLEAR_PATTERNS:
            if re.search(pattern, folder_name, re.IGNORECASE):
                return "clear"

        # 6. 기본값 (판정 불가)
        if len(folder_name) < 3:
            return "unclear"

        # 한글/영문 단어가 2개 이상이면 명확, 아니면 불명확
        words = re.findall(r"[가-힣]+|[a-zA-Z]+", folder_name)
        if len(words) >= 2:
            return "clear"

        return "unclear"

    def classify_all_folders(self, force: bool = False, on_progress=None):
        """
        DB의 모든 폴더에 대해 자동 분류 실행

        Args:
            force: True면 이미 분류된 폴더도 재분류 (기본: False)
            on_progress: 진행 콜백 (total, processed, current_folder)

        Returns:
            분류 결과 통계
        """
        # 모든 폴더 조회
        if force:
            # force=True: 모든 폴더 재분류
            query = text("""
                SELECT id, folder_path, file_count
                FROM folder_mappings
            """)
        else:
            # force=False: unknown/NULL 폴더만 분류
            query = text("""
                SELECT id, folder_path, file_count
                FROM folder_mappings
                WHERE folder_status = 'unknown' OR folder_status IS NULL
            """)
        folders = self.db.execute(query).fetchall()

        stats = {
            "clear": 0,
            "unclear": 0,
            "flat": 0,
            "nested": 0,
        }

        for folder in folders:
            folder_id = folder.id
            folder_path = folder.folder_path
            file_count = folder.file_count or 0

            # 서브폴더 조회 (같은 폴더 경로로 시작하는 다른 폴더)
            subfolders_query = text("""
                SELECT folder_path
                FROM folder_mappings
                WHERE folder_path LIKE :pattern
                AND id != :folder_id
                LIMIT 10
            """)
            subfolders = self.db.execute(
                subfolders_query,
                {"pattern": f"{folder_path}%", "folder_id": folder_id}
            ).fetchall()

            # 폴더 상태 판정
            status = self.classify_folder(
                folder_path,
                file_count,
                [sf.folder_path for sf in subfolders]
            )

            # DB 업데이트
            update_query = text("""
                UPDATE folder_mappings
                SET folder_status = :status
                WHERE id = :folder_id
            """)
            self.db.execute(update_query, {"status": status, "folder_id": folder_id})

            stats[status] += 1

            if on_progress:
                on_progress(len(folders), stats["clear"] + stats["unclear"] + stats["flat"] + stats["nested"], folder_path)

        self.db.commit()

        return {
            "total": len(folders),
            "clear": stats["clear"],
            "unclear": stats["unclear"],
            "flat": stats["flat"],
            "nested": stats["nested"],
        }
