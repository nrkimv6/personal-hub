"""
중복 이미지 감지 워커

- pHash Hamming distance로 유사도 판정 (≤10: 중복)
- SHA256 완전 일치도 별도 표시
- 중복 그룹 생성 및 품질 점수 계산
- 버킷 기반 비교로 O(n²) → O(n·k) 최적화 (84K 파일 대응)
- 배치 로딩으로 메모리 안전
- Resume 지원 (이미 처리된 파일 스킵)
"""

from pathlib import Path
from typing import List, Dict, Optional
from sqlalchemy import text
from sqlalchemy.orm import Session
from PIL import Image

from .phash import hamming_distance
from .task_progress import TaskProgressManager


# 배치 로딩 크기
BATCH_SIZE = 10000
# 버킷 프리픽스 길이 (hex 문자, 1 hex = 4 bits)
BUCKET_PREFIX_LEN = 8


class DuplicateDetector:
    """중복 이미지 감지 워커 — 버킷 기반 최적화"""

    def __init__(self, db: Session, settings):
        self.db = db
        self.threshold = settings.PHASH_DUPLICATE_THRESHOLD  # 기본 10
        self._cancelled = False

    def cancel(self):
        """외부에서 취소 요청"""
        self._cancelled = True

    async def detect_duplicates(self, resume: bool = True, progress_db: Session = None):
        """
        전체 이미지에서 중복 그룹 탐지 (버킷 기반)

        1. pHash가 계산된 파일을 배치로 로드
        2. pHash 상위 8자(32비트)로 버킷 분류
        3. 같은 버킷 + 인접 버킷 내에서만 비교
        4. threshold 이하이면 중복 그룹 생성

        Args:
            resume: True면 이미 duplicate_members에 있는 파일 스킵
            progress_db: 진행 추적용 별도 DB 세션 (None이면 self.db 사용)
        """
        print("[중복 감지] 시작")
        self._cancelled = False

        # 진행 추적
        p_db = progress_db or self.db
        progress_mgr = TaskProgressManager(p_db)

        # 전체 대상 수 조회
        count_query = self._build_count_query(resume)
        total_count = self.db.execute(text(count_query)).fetchone()[0]

        if total_count < 2:
            print(f"[중복 감지] 파일 수 부족 ({total_count}개, 2개 이상 필요)")
            return

        print(f"[중복 감지] 대상 파일: {total_count}개 (resume={resume})")
        task_id = progress_mgr.start_task('duplicate', total_count)

        # 버킷: prefix → [(file_id, phash, file_hash, file_size, file_path)]
        buckets: Dict[str, list] = {}
        file_to_group: Dict[int, int] = {}
        loaded = 0

        try:
            # Phase 1: 배치 로딩 → 버킷 빌드
            offset = 0
            while True:
                if self._cancelled:
                    print("[중복 감지] 취소됨")
                    progress_mgr.pause_task(task_id)
                    return

                batch = self._load_batch(offset, BATCH_SIZE, resume)
                if not batch:
                    break

                for row in batch:
                    prefix = row.phash[:BUCKET_PREFIX_LEN]
                    if prefix not in buckets:
                        buckets[prefix] = []
                    buckets[prefix].append(row)

                loaded += len(batch)
                offset += BATCH_SIZE
                print(f"[중복 감지] 로드: {loaded}/{total_count}")

            print(f"[중복 감지] 버킷 수: {len(buckets)}, 파일 수: {loaded}")

            # Phase 2: 버킷 내 비교 + 인접 버킷 비교
            processed = 0
            compared_pairs = set()  # (min_id, max_id) 중복 비교 방지

            for prefix, bucket_files in buckets.items():
                if self._cancelled:
                    progress_mgr.pause_task(task_id)
                    return

                # 같은 버킷 내 비교
                self._compare_within_bucket(
                    bucket_files, file_to_group, compared_pairs
                )

                # 인접 버킷 비교 (1-2비트 플립)
                for neighbor_prefix in self._get_neighbor_prefixes(prefix, flip_bits=2):
                    if neighbor_prefix in buckets and neighbor_prefix > prefix:
                        self._compare_cross_buckets(
                            bucket_files, buckets[neighbor_prefix],
                            file_to_group, compared_pairs
                        )

                processed += len(bucket_files)
                if processed % 5000 == 0 or processed == loaded:
                    progress_mgr.update_progress(task_id, processed, f"버킷 비교 중 ({processed}/{loaded})")

            progress_mgr.complete_task(task_id)
            group_count = len(set(file_to_group.values()))
            print(f"[중복 감지] 완료 — 그룹 수: {group_count}")

        except Exception as e:
            progress_mgr.fail_task(task_id, str(e))
            raise

    def _build_count_query(self, resume: bool) -> str:
        """대상 파일 수 카운트 쿼리"""
        base = """
            SELECT COUNT(*)
            FROM file_classifications fc
            JOIN image_features ifeat ON fc.id = ifeat.file_id
            WHERE ifeat.phash IS NOT NULL
        """
        if resume:
            base += " AND fc.id NOT IN (SELECT file_id FROM duplicate_members)"
        return base

    def _load_batch(self, offset: int, limit: int, resume: bool) -> list:
        """배치 로드 (LIMIT/OFFSET)"""
        query = """
            SELECT
                fc.id, fc.file_path, fc.file_hash, fc.file_size,
                ifeat.phash
            FROM file_classifications fc
            JOIN image_features ifeat ON fc.id = ifeat.file_id
            WHERE ifeat.phash IS NOT NULL
        """
        if resume:
            query += " AND fc.id NOT IN (SELECT file_id FROM duplicate_members)"
        query += " ORDER BY fc.id LIMIT :limit OFFSET :offset"

        return self.db.execute(
            text(query), {"limit": limit, "offset": offset}
        ).fetchall()

    def _compare_within_bucket(
        self, bucket_files: list, file_to_group: Dict[int, int],
        compared_pairs: set
    ):
        """버킷 내 O(k²) 비교 — k는 버킷 크기 (보통 3-5개)"""
        for i, row_a in enumerate(bucket_files):
            for row_b in bucket_files[i + 1:]:
                pair_key = (min(row_a.id, row_b.id), max(row_a.id, row_b.id))
                if pair_key in compared_pairs:
                    continue
                compared_pairs.add(pair_key)

                distance = hamming_distance(row_a.phash, row_b.phash)
                if distance <= self.threshold:
                    self._register_duplicate(
                        file_to_group, row_a, row_b, distance
                    )

    def _compare_cross_buckets(
        self, bucket_a: list, bucket_b: list,
        file_to_group: Dict[int, int], compared_pairs: set
    ):
        """두 버킷 간 교차 비교"""
        for row_a in bucket_a:
            for row_b in bucket_b:
                pair_key = (min(row_a.id, row_b.id), max(row_a.id, row_b.id))
                if pair_key in compared_pairs:
                    continue
                compared_pairs.add(pair_key)

                distance = hamming_distance(row_a.phash, row_b.phash)
                if distance <= self.threshold:
                    self._register_duplicate(
                        file_to_group, row_a, row_b, distance
                    )

    def _get_neighbor_prefixes(self, prefix: str, flip_bits: int = 2) -> List[str]:
        """
        인접 프리픽스 생성 — 상위 hex의 각 비트를 플립

        Args:
            prefix: 8자리 hex 프리픽스
            flip_bits: 최대 플립할 비트 수

        Returns:
            이웃 프리픽스 리스트
        """
        neighbors = []
        prefix_int = int(prefix, 16)
        total_bits = len(prefix) * 4  # hex 1자 = 4비트

        # 1비트 플립
        for bit_pos in range(total_bits):
            flipped = prefix_int ^ (1 << bit_pos)
            neighbor = format(flipped, f'0{len(prefix)}x')
            neighbors.append(neighbor)

        # 2비트 플립 (조합)
        if flip_bits >= 2:
            for i in range(total_bits):
                for j in range(i + 1, total_bits):
                    flipped = prefix_int ^ (1 << i) ^ (1 << j)
                    neighbor = format(flipped, f'0{len(prefix)}x')
                    neighbors.append(neighbor)

        return neighbors

    def _register_duplicate(
        self, file_to_group: Dict[int, int],
        row_a, row_b, distance: int
    ):
        """중복 쌍을 그룹에 등록"""
        group_id = self._get_or_create_group(
            file_to_group, row_a.id, row_b.id, row_a.phash
        )
        is_exact = row_a.file_hash == row_b.file_hash

        self._add_duplicate_member(
            group_id, row_a.id, distance, is_exact,
            row_a.file_size, row_a.file_path
        )
        self._add_duplicate_member(
            group_id, row_b.id, distance, is_exact,
            row_b.file_size, row_b.file_path
        )

    def _get_or_create_group(
        self,
        file_to_group: Dict[int, int],
        file_a_id: int,
        file_b_id: int,
        representative_phash: str
    ) -> int:
        """중복 그룹 가져오기 또는 생성"""
        if file_a_id in file_to_group:
            group_id = file_to_group[file_a_id]
            file_to_group[file_b_id] = group_id
            return group_id

        if file_b_id in file_to_group:
            group_id = file_to_group[file_b_id]
            file_to_group[file_a_id] = group_id
            return group_id

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
        """중복 멤버 추가 (이미 존재하면 스킵)"""
        exists = self.db.execute(
            text("SELECT 1 FROM duplicate_members WHERE group_id = :gid AND file_id = :fid"),
            {"gid": group_id, "fid": file_id}
        ).fetchone()

        if exists:
            return

        resolution = self._get_image_resolution(file_path)
        quality_score = self._calculate_quality_score(resolution, file_size)

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
        """이미지 해상도 추출"""
        try:
            with Image.open(file_path) as img:
                return f"{img.width}x{img.height}"
        except Exception:
            return "unknown"

    def _calculate_quality_score(self, resolution: str, file_size: int) -> float:
        """품질 점수 = (가로 × 세로) × (파일 크기 MB)"""
        try:
            if resolution == "unknown":
                return 0.0
            width, height = map(int, resolution.split("x"))
            return width * height * (file_size / (1024 * 1024))
        except Exception:
            return 0.0


async def resolve_duplicate_group(
    db: Session,
    group_id: int,
    keep_file_id: int
):
    """중복 그룹 해결 (사용자 선택)"""
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
