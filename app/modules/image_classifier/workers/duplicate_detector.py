"""
중복 이미지 감지 워커

- pHash Hamming distance로 유사도 판정 (≤10: 중복)
- SHA256 완전 일치도 별도 표시
- 중복 그룹 생성 및 품질 점수 계산
"""

from pathlib import Path
from typing import List, Dict
from sqlalchemy import text
from sqlalchemy.orm import Session
from PIL import Image

from .phash import hamming_distance


class DuplicateDetector:
    """중복 이미지 감지 워커"""

    def __init__(self, db: Session, settings):
        self.db = db
        self.threshold = settings.PHASH_DUPLICATE_THRESHOLD  # 기본 10

    async def detect_duplicates(self):
        """
        전체 이미지에서 중복 그룹 탐지

        1. pHash가 계산된 모든 파일 조회
        2. pHash 간 Hamming distance 계산
        3. threshold 이하이면 중복 그룹 생성
        4. SHA256 해시로 완전 일치 여부 확인
        5. 품질 점수 계산 (해상도 × 파일크기)
        """
        print("[중복 감지] 시작")

        # pHash가 있는 모든 파일 조회
        result = self.db.execute(
            text("""
                SELECT
                    fc.id, fc.file_path, fc.file_hash, fc.file_size,
                    ifeat.phash
                FROM file_classifications fc
                JOIN image_features ifeat ON fc.id = ifeat.file_id
                WHERE ifeat.phash IS NOT NULL
                ORDER BY fc.id
            """)
        ).fetchall()

        if len(result) < 2:
            print("[중복 감지] 파일 수 부족 (2개 이상 필요)")
            return

        print(f"[중복 감지] 대상 파일: {len(result)}개")

        # 중복 그룹 매핑 (file_id → group_id)
        file_to_group: Dict[int, int] = {}

        # 전수 비교 (향후 pHash 인덱싱으로 최적화 가능)
        for i, row_a in enumerate(result):
            for row_b in result[i+1:]:
                distance = hamming_distance(row_a.phash, row_b.phash)

                if distance <= self.threshold:
                    # 중복으로 판정
                    group_id = self._get_or_create_group(
                        file_to_group, row_a.id, row_b.id, row_a.phash
                    )

                    # 중복 멤버 추가
                    self._add_duplicate_member(
                        group_id, row_a.id, distance,
                        row_a.file_hash == row_b.file_hash,  # SHA256 완전 일치 여부
                        row_a.file_size, row_a.file_path
                    )
                    self._add_duplicate_member(
                        group_id, row_b.id, distance,
                        row_a.file_hash == row_b.file_hash,
                        row_b.file_size, row_b.file_path
                    )

        print(f"[중복 감지] 완료 — 그룹 수: {len(set(file_to_group.values()))}")

    def _get_or_create_group(
        self,
        file_to_group: Dict[int, int],
        file_a_id: int,
        file_b_id: int,
        representative_phash: str
    ) -> int:
        """
        중복 그룹 가져오기 또는 생성

        Args:
            file_to_group: 파일 ID → 그룹 ID 매핑
            file_a_id, file_b_id: 중복 파일 ID
            representative_phash: 대표 pHash

        Returns:
            group_id
        """
        # 이미 그룹에 속해 있는지 확인
        if file_a_id in file_to_group:
            group_id = file_to_group[file_a_id]
            file_to_group[file_b_id] = group_id
            return group_id

        if file_b_id in file_to_group:
            group_id = file_to_group[file_b_id]
            file_to_group[file_a_id] = group_id
            return group_id

        # 신규 그룹 생성
        result = self.db.execute(
            text("""
                INSERT INTO duplicate_groups (group_hash, member_count, status)
                VALUES (:phash, 0, 'pending')
                RETURNING id
            """),
            {"phash": representative_phash}
        ).fetchone()
        self.db.commit()

        group_id = result.id
        file_to_group[file_a_id] = group_id
        file_to_group[file_b_id] = group_id

        return group_id

    def _add_duplicate_member(
        self,
        group_id: int,
        file_id: int,
        phash_distance: int,
        is_exact: bool,
        file_size: int,
        file_path: str
    ):
        """
        중복 멤버 추가

        Args:
            group_id: 중복 그룹 ID
            file_id: 파일 ID
            phash_distance: pHash Hamming distance
            is_exact: SHA256 완전 일치 여부
            file_size: 파일 크기
            file_path: 파일 경로
        """
        # 중복 체크 (이미 추가된 경우 스킵)
        exists = self.db.execute(
            text("SELECT 1 FROM duplicate_members WHERE group_id = :gid AND file_id = :fid"),
            {"gid": group_id, "fid": file_id}
        ).fetchone()

        if exists:
            return

        # 해상도 추출
        resolution = self._get_image_resolution(file_path)

        # 품질 점수 계산 (해상도 × 파일크기)
        quality_score = self._calculate_quality_score(resolution, file_size)

        # 삽입
        self.db.execute(
            text("""
                INSERT INTO duplicate_members (
                    group_id, file_id, phash_distance, is_exact,
                    file_size, resolution, quality_score
                ) VALUES (
                    :group_id, :file_id, :distance, :is_exact,
                    :file_size, :resolution, :quality_score
                )
            """),
            {
                "group_id": group_id,
                "file_id": file_id,
                "distance": phash_distance,
                "is_exact": is_exact,
                "file_size": file_size,
                "resolution": resolution,
                "quality_score": quality_score,
            }
        )

        # 그룹 멤버 수 업데이트
        self.db.execute(
            text("""
                UPDATE duplicate_groups
                SET member_count = (
                    SELECT COUNT(*) FROM duplicate_members WHERE group_id = :gid
                )
                WHERE id = :gid
            """),
            {"gid": group_id}
        )

        self.db.commit()

    def _get_image_resolution(self, file_path: str) -> str:
        """
        이미지 해상도 추출

        Returns:
            "1920x1080" 형식 또는 "unknown"
        """
        try:
            with Image.open(file_path) as img:
                return f"{img.width}x{img.height}"
        except Exception:
            return "unknown"

    def _calculate_quality_score(self, resolution: str, file_size: int) -> float:
        """
        품질 점수 계산

        품질 점수 = (가로 × 세로) × (파일 크기 / 1MB)

        Args:
            resolution: "1920x1080" 형식
            file_size: 파일 크기 (bytes)

        Returns:
            품질 점수 (float)
        """
        try:
            if resolution == "unknown":
                return 0.0

            width, height = map(int, resolution.split("x"))
            pixels = width * height

            # 파일 크기를 MB로 변환
            file_size_mb = file_size / (1024 * 1024)

            return pixels * file_size_mb

        except Exception:
            return 0.0


async def resolve_duplicate_group(
    db: Session,
    group_id: int,
    keep_file_id: int
):
    """
    중복 그룹 해결 (사용자 선택)

    Args:
        db: DB 세션
        group_id: 중복 그룹 ID
        keep_file_id: 보관할 파일 ID
    """
    # kept_file_id 업데이트
    db.execute(
        text("""
            UPDATE duplicate_groups
            SET status = 'resolved', kept_file_id = :keep_id
            WHERE id = :group_id
        """),
        {"group_id": group_id, "keep_id": keep_file_id}
    )
    db.commit()

    print(f"[중복 해결] 그룹 {group_id} — 보관: {keep_file_id}")
