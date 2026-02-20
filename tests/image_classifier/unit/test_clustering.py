"""시간 클러스터링 테스트"""
import pytest
from datetime import datetime, timedelta
from sqlalchemy import text
from app.modules.image_classifier.workers.clustering import TimeClusteringWorker


@pytest.fixture
def clustering_worker(test_db):
    """클러스터링 워커 생성"""
    return TimeClusteringWorker(test_db, gap_minutes=60)


# ================================================
# Right: 기본 동작
# ================================================

def test_cluster_by_60min_gap(clustering_worker, test_db):
    """13.1 Right: 60분 이내 → 같은 클러스터"""
    base_time = datetime(2023, 4, 15, 10, 0, 0)

    # 3개 파일 생성 (10:00, 10:30, 10:50 - 모두 60분 이내)
    for i, offset_minutes in enumerate([0, 30, 50]):
        time = base_time + timedelta(minutes=offset_minutes)
        test_db.execute(text("""
            INSERT INTO file_classifications (id, file_path, file_hash, status, extracted_date)
            VALUES (:id, :path, 'hash', 'pending', :date)
        """), {"id": i+1, "path": f"/test/file{i+1}.jpg", "date": time.isoformat()})

    test_db.commit()

    # 클러스터링 실행
    result = clustering_worker.cluster_all_unclassified()

    # 1개 클러스터 생성되어야 함
    assert result["clusters"] == 1
    assert result["clustered_files"] == 3


def test_cluster_split_at_gap(clustering_worker, test_db):
    """13.2 Right: 61분 → 다른 클러스터"""
    base_time = datetime(2023, 4, 15, 10, 0, 0)

    # 2개 파일 생성 (10:00, 11:01 - 61분 차이)
    test_db.execute(text("""
        INSERT INTO file_classifications (id, file_path, file_hash, status, extracted_date)
        VALUES (1, '/test/file1.jpg', 'hash', 'pending', :date1)
    """), {"date1": base_time.isoformat()})

    test_db.execute(text("""
        INSERT INTO file_classifications (id, file_path, file_hash, status, extracted_date)
        VALUES (2, '/test/file2.jpg', 'hash', 'pending', :date2)
    """), {"date2": (base_time + timedelta(minutes=61)).isoformat()})

    test_db.commit()

    # 클러스터링 실행
    result = clustering_worker.cluster_all_unclassified()

    # 2개 클러스터 생성되어야 함
    assert result["clusters"] == 2


def test_cluster_count_and_range(clustering_worker, test_db):
    """13.3 Right: 시작/종료 시간, 파일 수"""
    base_time = datetime(2023, 4, 15, 10, 0, 0)

    # 4개 파일 생성 (10:00 ~ 10:30)
    for i in range(4):
        time = base_time + timedelta(minutes=i * 10)
        test_db.execute(text("""
            INSERT INTO file_classifications (id, file_path, file_hash, status, extracted_date)
            VALUES (:id, :path, 'hash', 'pending', :date)
        """), {"id": i+1, "path": f"/test/file{i+1}.jpg", "date": time.isoformat()})

    test_db.commit()

    # 클러스터링 실행
    clustering_worker.cluster_all_unclassified()

    # 클러스터 정보 조회
    cluster = test_db.execute(text("SELECT * FROM time_clusters LIMIT 1")).fetchone()

    assert cluster.file_count == 4
    assert cluster.date == "2023-04-15"
    # start_time: 10:00, end_time: 10:30
    assert "10:00" in cluster.start_time
    assert "10:30" in cluster.end_time


def test_sample_selection_3_or_less(clustering_worker, test_db):
    """13.4 Right: N≤3 → 전체 반환"""
    base_time = datetime(2023, 4, 15, 10, 0, 0)

    # 3개 파일 생성
    for i in range(3):
        time = base_time + timedelta(minutes=i * 10)
        test_db.execute(text("""
            INSERT INTO file_classifications (id, file_path, file_hash, status, extracted_date)
            VALUES (:id, :path, 'hash', 'pending', :date)
        """), {"id": i+1, "path": f"/test/file{i+1}.jpg", "date": time.isoformat()})

    test_db.commit()

    # 클러스터링 실행
    clustering_worker.cluster_all_unclassified()

    # 클러스터 ID 조회
    cluster = test_db.execute(text("SELECT id FROM time_clusters LIMIT 1")).fetchone()
    cluster_id = cluster.id

    # 샘플 선택
    samples = clustering_worker.get_cluster_samples(cluster_id)

    # 3개 모두 반환
    assert len(samples) == 3
    assert samples == [1, 2, 3]


def test_sample_selection_4_to_10(clustering_worker, test_db):
    """13.5 Right: 4≤N≤10 → 첫/중간/끝"""
    base_time = datetime(2023, 4, 15, 10, 0, 0)

    # 7개 파일 생성
    for i in range(7):
        time = base_time + timedelta(minutes=i * 5)
        test_db.execute(text("""
            INSERT INTO file_classifications (id, file_path, file_hash, status, extracted_date)
            VALUES (:id, :path, 'hash', 'pending', :date)
        """), {"id": i+1, "path": f"/test/file{i+1}.jpg", "date": time.isoformat()})

    test_db.commit()

    # 클러스터링 실행
    clustering_worker.cluster_all_unclassified()

    # 클러스터 ID 조회
    cluster = test_db.execute(text("SELECT id FROM time_clusters LIMIT 1")).fetchone()
    cluster_id = cluster.id

    # 샘플 선택
    samples = clustering_worker.get_cluster_samples(cluster_id)

    # 첫/중간/끝 3장
    assert len(samples) == 3
    assert samples[0] == 1  # 첫 번째
    assert samples[1] == 4  # 중간 (7 // 2 = 3, 0-indexed)
    assert samples[2] == 7  # 마지막


def test_sample_selection_over_10(clustering_worker, test_db):
    """13.6 Right: N>10 → 균등 간격"""
    base_time = datetime(2023, 4, 15, 10, 0, 0)

    # 15개 파일 생성
    for i in range(15):
        time = base_time + timedelta(minutes=i * 2)
        test_db.execute(text("""
            INSERT INTO file_classifications (id, file_path, file_hash, status, extracted_date)
            VALUES (:id, :path, 'hash', 'pending', :date)
        """), {"id": i+1, "path": f"/test/file{i+1}.jpg", "date": time.isoformat()})

    test_db.commit()

    # 클러스터링 실행
    clustering_worker.cluster_all_unclassified()

    # 클러스터 ID 조회
    cluster = test_db.execute(text("SELECT id FROM time_clusters LIMIT 1")).fetchone()
    cluster_id = cluster.id

    # 샘플 선택 (max_samples=5)
    samples = clustering_worker.get_cluster_samples(cluster_id, max_samples=5)

    # 균등 간격 5장
    assert len(samples) == 5
    # step = 15 // 5 = 3
    # 예상: [1, 4, 7, 10, 13] (0-indexed: 0*3, 1*3, 2*3, 3*3, 4*3)


# ================================================
# Boundary: 경계 조건
# ================================================

def test_gap_boundary_59_min(clustering_worker, test_db):
    """13.7 Boundary: 59분 → 같은 클러스터"""
    base_time = datetime(2023, 4, 15, 10, 0, 0)

    # 2개 파일 생성 (10:00, 10:59)
    test_db.execute(text("""
        INSERT INTO file_classifications (id, file_path, file_hash, status, extracted_date)
        VALUES (1, '/test/file1.jpg', 'hash', 'pending', :date1)
    """), {"date1": base_time.isoformat()})

    test_db.execute(text("""
        INSERT INTO file_classifications (id, file_path, file_hash, status, extracted_date)
        VALUES (2, '/test/file2.jpg', 'hash', 'pending', :date2)
    """), {"date2": (base_time + timedelta(minutes=59)).isoformat()})

    test_db.commit()

    # 클러스터링 실행
    result = clustering_worker.cluster_all_unclassified()

    # 1개 클러스터
    assert result["clusters"] == 1


def test_gap_boundary_60_min(clustering_worker, test_db):
    """13.8 Boundary: 60분 → 같은 클러스터"""
    base_time = datetime(2023, 4, 15, 10, 0, 0)

    # 2개 파일 생성 (10:00, 11:00)
    test_db.execute(text("""
        INSERT INTO file_classifications (id, file_path, file_hash, status, extracted_date)
        VALUES (1, '/test/file1.jpg', 'hash', 'pending', :date1)
    """), {"date1": base_time.isoformat()})

    test_db.execute(text("""
        INSERT INTO file_classifications (id, file_path, file_hash, status, extracted_date)
        VALUES (2, '/test/file2.jpg', 'hash', 'pending', :date2)
    """), {"date2": (base_time + timedelta(minutes=60)).isoformat()})

    test_db.commit()

    # 클러스터링 실행
    result = clustering_worker.cluster_all_unclassified()

    # 1개 클러스터 (60분까지는 같은 클러스터)
    assert result["clusters"] == 1


def test_gap_boundary_61_min(clustering_worker, test_db):
    """13.9 Boundary: 61분 → 다른 클러스터"""
    base_time = datetime(2023, 4, 15, 10, 0, 0)

    # 2개 파일 생성 (10:00, 11:01)
    test_db.execute(text("""
        INSERT INTO file_classifications (id, file_path, file_hash, status, extracted_date)
        VALUES (1, '/test/file1.jpg', 'hash', 'pending', :date1)
    """), {"date1": base_time.isoformat()})

    test_db.execute(text("""
        INSERT INTO file_classifications (id, file_path, file_hash, status, extracted_date)
        VALUES (2, '/test/file2.jpg', 'hash', 'pending', :date2)
    """), {"date2": (base_time + timedelta(minutes=61)).isoformat()})

    test_db.commit()

    # 클러스터링 실행
    result = clustering_worker.cluster_all_unclassified()

    # 2개 클러스터 (61분은 분리)
    assert result["clusters"] == 2


def test_no_date_files_excluded(clustering_worker, test_db):
    """13.10 Boundary: extracted_date=NULL → 제외"""
    # 날짜 없는 파일 생성
    test_db.execute(text("""
        INSERT INTO file_classifications (id, file_path, file_hash, status)
        VALUES (1, '/test/file1.jpg', 'hash', 'pending')
    """))

    test_db.commit()

    # 클러스터링 실행
    result = clustering_worker.cluster_all_unclassified()

    # 클러스터링 대상 없음
    assert result["total"] == 0


def test_single_file_cluster(clustering_worker, test_db):
    """13.11 Boundary: 파일 1개 → 클러스터 1개"""
    base_time = datetime(2023, 4, 15, 10, 0, 0)

    # 1개 파일 생성
    test_db.execute(text("""
        INSERT INTO file_classifications (id, file_path, file_hash, status, extracted_date)
        VALUES (1, '/test/file1.jpg', 'hash', 'pending', :date)
    """), {"date": base_time.isoformat()})

    test_db.commit()

    # 클러스터링 실행
    result = clustering_worker.cluster_all_unclassified()

    # 1개 클러스터, 1개 파일
    assert result["clusters"] == 1
    assert result["clustered_files"] == 1


# ================================================
# Error: 예외 처리
# ================================================

def test_no_pending_files(clustering_worker, test_db):
    """13.12 Error: 미분류 파일 없음 → total=0"""
    # 파일 없이 클러스터링 실행
    result = clustering_worker.cluster_all_unclassified()

    assert result["total"] == 0
    assert result["clusters"] == 0


# ================================================
# Inverse: 클러스터 분류 → 파일 상태 전환
# ================================================

def test_cluster_all_rebuilds_from_scratch(test_db):
    """13.14 Right: cluster_all() — 기존 클러스터 삭제 후 전체 재생성"""
    base_time = datetime(2023, 4, 15, 10, 0, 0)
    worker = TimeClusteringWorker(test_db, gap_minutes=60)

    # 3개 파일 생성
    for i in range(3):
        time = base_time + timedelta(minutes=i * 10)
        test_db.execute(text("""
            INSERT INTO file_classifications (id, file_path, file_hash, status, extracted_date)
            VALUES (:id, :path, 'hash', 'pending', :date)
        """), {"id": i+1, "path": f"/test/file{i+1}.jpg", "date": time.isoformat()})
    test_db.commit()

    # 1차 클러스터링 (unclassified)
    result1 = worker.cluster_all_unclassified()
    assert result1["clusters"] == 1

    # cluster_all로 전체 재생성
    result2 = worker.cluster_all()
    assert result2["clusters"] == 1
    assert result2["clustered_files"] == 3

    # 기존 클러스터 1개만 있어야 함 (중복 없음)
    count = test_db.execute(text("SELECT COUNT(*) FROM time_clusters")).scalar()
    assert count == 1


def test_cluster_all_preserves_category(test_db):
    """13.15 Right: cluster_all() — 기존 final_category_id 보존"""
    base_time = datetime(2023, 4, 15, 10, 0, 0)
    worker = TimeClusteringWorker(test_db, gap_minutes=60)

    # 카테고리 생성
    test_db.execute(text("INSERT INTO categories (id, name, full_path) VALUES (1, 'Travel', 'Travel')"))

    # 이미 분류된 파일 생성
    test_db.execute(text("""
        INSERT INTO file_classifications (id, file_path, file_hash, status, extracted_date, final_category_id)
        VALUES (1, '/test/file1.jpg', 'hash', 'ai_classified', :date, 1)
    """), {"date": base_time.isoformat()})
    test_db.commit()

    # 전체 재클러스터링
    result = worker.cluster_all()
    assert result["clustered_files"] == 1

    # final_category_id가 보존되어야 함
    row = test_db.execute(text("SELECT final_category_id FROM file_classifications WHERE id = 1")).fetchone()
    assert row.final_category_id == 1


def test_cluster_all_includes_classified_files(test_db):
    """13.16 Boundary: cluster_all() — 이미 분류된 파일도 포함"""
    base_time = datetime(2023, 4, 15, 10, 0, 0)
    worker = TimeClusteringWorker(test_db, gap_minutes=60)

    # 분류된 파일 + 미분류 파일
    test_db.execute(text("""
        INSERT INTO file_classifications (id, file_path, file_hash, status, extracted_date, final_category_id)
        VALUES (1, '/test/file1.jpg', 'h1', 'ai_classified', :date1, 1),
               (2, '/test/file2.jpg', 'h2', 'pending', :date2, NULL)
    """), {"date1": base_time.isoformat(), "date2": (base_time + timedelta(minutes=10)).isoformat()})
    test_db.execute(text("INSERT INTO categories (id, name, full_path) VALUES (1, 'A', 'A')"))
    test_db.commit()

    # cluster_all_unclassified는 분류된 파일 제외
    result_new = worker.cluster_all_unclassified()
    assert result_new["clustered_files"] == 1  # 미분류만

    # cluster_all은 모두 포함
    result_all = worker.cluster_all()
    assert result_all["clustered_files"] == 2  # 전체


def test_cluster_all_on_progress_called(test_db):
    """13.17 Right: cluster_all() — on_progress 콜백 호출"""
    base_time = datetime(2023, 4, 15, 10, 0, 0)
    worker = TimeClusteringWorker(test_db, gap_minutes=60)

    for i in range(3):
        time = base_time + timedelta(minutes=i * 10)
        test_db.execute(text("""
            INSERT INTO file_classifications (id, file_path, file_hash, status, extracted_date)
            VALUES (:id, :path, 'hash', 'pending', :date)
        """), {"id": i+1, "path": f"/test/file{i+1}.jpg", "date": time.isoformat()})
    test_db.commit()

    progress_calls = []
    def on_progress(processed, total):
        progress_calls.append((processed, total))

    worker.cluster_all(on_progress=on_progress)
    assert len(progress_calls) > 0
    # 마지막 콜의 processed == total
    assert progress_calls[-1][0] == progress_calls[-1][1]


def test_mark_cluster_classified(clustering_worker, test_db):
    """13.13 Inverse: 클러스터 분류 → 파일 상태 전환"""
    base_time = datetime(2023, 4, 15, 10, 0, 0)

    # 카테고리 생성
    test_db.execute(text("""
        INSERT INTO categories (id, name, full_path) VALUES (1, 'Travel', 'Travel')
    """))

    # 3개 파일 생성
    for i in range(3):
        time = base_time + timedelta(minutes=i * 10)
        test_db.execute(text("""
            INSERT INTO file_classifications (id, file_path, file_hash, status, extracted_date)
            VALUES (:id, :path, 'hash', 'pending', :date)
        """), {"id": i+1, "path": f"/test/file{i+1}.jpg", "date": time.isoformat()})

    test_db.commit()

    # 클러스터링 실행
    clustering_worker.cluster_all_unclassified()

    # 클러스터 ID 조회
    cluster = test_db.execute(text("SELECT id FROM time_clusters LIMIT 1")).fetchone()
    cluster_id = cluster.id

    # 클러스터 분류
    clustering_worker.mark_cluster_classified(cluster_id, category_id=1, classified_by="ai")

    # 클러스터 상태 확인
    cluster_info = clustering_worker.get_cluster_info(cluster_id)
    assert cluster_info["is_classified"] == 1
    assert cluster_info["category_id"] == 1
