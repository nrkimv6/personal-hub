"""
시간 클러스터링 워커

날짜/시간 기준으로 이미지를 클러스터로 묶음
- 1시간 이내 촬영 = 같은 이벤트/장소로 간주
- 클러스터별 대표 샘플 선택 → AI 분류
"""

from datetime import datetime, timedelta
from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import text


class TimeClusteringWorker:
    """시간 클러스터링 워커"""

    def __init__(self, db: Session, gap_minutes: int = 60):
        """
        Args:
            db: DB 세션
            gap_minutes: 클러스터 간 최소 시간 갭 (분)
        """
        self.db = db
        self.gap_minutes = gap_minutes

    def cluster_all(self, on_progress: Optional[callable] = None) -> dict:
        """
        전체 파일 재클러스터링 (기존 클러스터 삭제 후 전체 재생성)

        기존 final_category_id는 보존 (클러스터만 재생성, 분류는 유지)

        Args:
            on_progress: 진행 콜백 (processed, total)

        Returns:
            통계 정보
        """
        print(f"[시간 클러스터링] 전체 재생성 시작 (갭: {self.gap_minutes}분)")

        # 기존 클러스터 삭제
        self.db.execute(text("UPDATE file_classifications SET cluster_id = NULL"))
        self.db.execute(text("DELETE FROM time_clusters"))
        self.db.flush()

        # 날짜 정보가 있는 모든 파일 조회
        query = text("""
            SELECT id, file_path, user_date, extracted_date
            FROM file_classifications
            WHERE (user_date IS NOT NULL OR extracted_date IS NOT NULL)
            ORDER BY COALESCE(user_date, extracted_date)
        """)
        files = self.db.execute(query).fetchall()

        return self._do_clustering(files, on_progress=on_progress, label="전체 재생성")

    def cluster_all_unclassified(self, on_progress: Optional[callable] = None) -> dict:
        """
        미분류 파일을 시간 기준으로 클러스터링

        Args:
            on_progress: 진행 콜백 (processed, total)

        Returns:
            통계 정보
        """
        print(f"[시간 클러스터링] 시작 (갭: {self.gap_minutes}분)")

        # 미분류 파일 조회 (날짜 정보가 있는 파일만)
        query = text("""
            SELECT id, file_path, user_date, extracted_date
            FROM file_classifications
            WHERE (status = 'pending' OR final_category_id IS NULL)
            AND (user_date IS NOT NULL OR extracted_date IS NOT NULL)
            AND cluster_id IS NULL
            ORDER BY COALESCE(user_date, extracted_date)
        """)
        files = self.db.execute(query).fetchall()

        return self._do_clustering(files, on_progress=on_progress, label="미분류")

    def _do_clustering(
        self,
        files,
        on_progress: Optional[callable] = None,
        label: str = "",
    ) -> dict:
        """
        클러스터링 공통 로직

        Args:
            files: 파일 목록 (id, file_path, user_date, extracted_date)
            on_progress: 진행 콜백 (processed, total)
            label: 로그용 라벨

        Returns:
            통계 정보
        """
        if not files:
            print(f"[시간 클러스터링] 클러스터링할 파일이 없습니다. ({label})")
            return {"total": 0, "clusters": 0, "clustered_files": 0}

        total = len(files)
        print(f"[시간 클러스터링] 대상 파일: {total}개 ({label})")

        # 클러스터링
        clusters = []
        current_cluster = []
        prev_time = None

        for file in files:
            file_id = file.id
            file_date = file.user_date or file.extracted_date

            # 날짜 문자열 → datetime
            if isinstance(file_date, str):
                try:
                    file_time = datetime.fromisoformat(file_date)
                except Exception:
                    file_time = datetime.strptime(file_date, "%Y-%m-%d")
            else:
                file_time = file_date

            # 첫 파일
            if prev_time is None:
                current_cluster.append((file_id, file_time, file.file_path))
                prev_time = file_time
                continue

            # 시간 갭 계산
            gap = (file_time - prev_time).total_seconds() / 60

            # 갭이 기준 이상이면 새 클러스터 시작
            if gap > self.gap_minutes:
                clusters.append(current_cluster)
                current_cluster = [(file_id, file_time, file.file_path)]
            else:
                current_cluster.append((file_id, file_time, file.file_path))

            prev_time = file_time

        # 마지막 클러스터 추가
        if current_cluster:
            clusters.append(current_cluster)

        print(f"[시간 클러스터링] 클러스터 생성 완료: {len(clusters)}개")

        # DB에 저장
        clustered_files = 0
        for cluster_files in clusters:
            if not cluster_files:
                continue

            # 클러스터 정보 추출
            start_time = cluster_files[0][1]
            end_time = cluster_files[-1][1]
            date_str = start_time.strftime("%Y-%m-%d")
            file_count = len(cluster_files)

            # 클러스터 생성
            insert_cluster_query = text("""
                INSERT INTO time_clusters (date, start_time, end_time, file_count, is_classified)
                VALUES (:date, :start_time, :end_time, :file_count, 0)
            """)
            self.db.execute(insert_cluster_query, {
                "date": date_str,
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "file_count": file_count,
            })
            self.db.flush()

            # 생성된 클러스터 ID 조회
            cluster_id_query = text("""
                SELECT id FROM time_clusters
                WHERE date = :date AND start_time = :start_time
                ORDER BY id DESC LIMIT 1
            """)
            cluster_id = self.db.execute(cluster_id_query, {
                "date": date_str,
                "start_time": start_time.isoformat(),
            }).fetchone().id

            # 파일에 클러스터 ID 할당
            for file_id, _, _ in cluster_files:
                update_query = text("""
                    UPDATE file_classifications
                    SET cluster_id = :cluster_id
                    WHERE id = :file_id
                """)
                self.db.execute(update_query, {"cluster_id": cluster_id, "file_id": file_id})
                clustered_files += 1

            if on_progress:
                on_progress(clustered_files, total)

        self.db.commit()

        print(f"[시간 클러스터링] 완료: {clustered_files}개 파일을 {len(clusters)}개 클러스터로 분류 ({label})")

        return {
            "total": total,
            "clusters": len(clusters),
            "clustered_files": clustered_files,
        }

    def get_cluster_samples(
        self,
        cluster_id: int,
        max_samples: int = 5,
    ) -> List[int]:
        """
        클러스터의 대표 샘플 파일 ID 선택

        전략:
        - N ≤ 3: 전체
        - N ≤ 10: 첫/중간/끝 3장
        - N > 10: 균등 간격 5장 (또는 max_samples)

        Args:
            cluster_id: 클러스터 ID
            max_samples: 최대 샘플 수

        Returns:
            파일 ID 리스트
        """
        # 클러스터 파일 조회
        query = text("""
            SELECT id
            FROM file_classifications
            WHERE cluster_id = :cluster_id
            ORDER BY COALESCE(user_date, extracted_date)
        """)
        files = self.db.execute(query, {"cluster_id": cluster_id}).fetchall()
        file_ids = [f.id for f in files]

        n = len(file_ids)

        if n == 0:
            return []

        if n <= 3:
            # 전체 반환
            return file_ids

        if n <= 10:
            # 첫/중간/끝 3장
            return [file_ids[0], file_ids[n // 2], file_ids[-1]]

        # 균등 간격 샘플링
        step = n // max_samples
        samples = [file_ids[i * step] for i in range(max_samples)]

        return samples

    def get_cluster_info(self, cluster_id: int) -> Optional[dict]:
        """
        클러스터 정보 조회

        Args:
            cluster_id: 클러스터 ID

        Returns:
            클러스터 정보 딕셔너리
        """
        query = text("""
            SELECT id, date, start_time, end_time, file_count, category_id, is_classified
            FROM time_clusters
            WHERE id = :cluster_id
        """)
        cluster = self.db.execute(query, {"cluster_id": cluster_id}).fetchone()

        if not cluster:
            return None

        return {
            "id": cluster.id,
            "date": cluster.date,
            "start_time": cluster.start_time,
            "end_time": cluster.end_time,
            "file_count": cluster.file_count,
            "category_id": cluster.category_id,
            "is_classified": cluster.is_classified,
        }

    def mark_cluster_classified(
        self,
        cluster_id: int,
        category_id: int,
        classified_by: str = "ai",
    ):
        """
        클러스터를 분류 완료로 표시

        Args:
            cluster_id: 클러스터 ID
            category_id: 할당된 카테고리 ID
            classified_by: 분류 주체 (ai/user)
        """
        # 클러스터 업데이트
        update_cluster_query = text("""
            UPDATE time_clusters
            SET category_id = :category_id,
                is_classified = 1,
                classified_by = :classified_by
            WHERE id = :cluster_id
        """)
        self.db.execute(update_cluster_query, {
            "category_id": category_id,
            "classified_by": classified_by,
            "cluster_id": cluster_id,
        })

        # 클러스터의 모든 파일에 카테고리 할당
        update_files_query = text("""
            UPDATE file_classifications
            SET final_category_id = :category_id,
                ai_category_id = :category_id,
                status = 'ai_classified'
            WHERE cluster_id = :cluster_id
            AND (status = 'pending' OR final_category_id IS NULL)
        """)
        self.db.execute(update_files_query, {
            "category_id": category_id,
            "cluster_id": cluster_id,
        })

        self.db.commit()

        print(f"[시간 클러스터링] 클러스터 {cluster_id} → 카테고리 {category_id} 할당 완료")
