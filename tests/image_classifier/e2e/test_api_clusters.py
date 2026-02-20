"""클러스터 API 엔드포인트 테스트"""
import pytest
from sqlalchemy import text
from datetime import datetime


@pytest.fixture
def seeded_clusters(test_db):
    """클러스터 및 파일 데이터 생성"""
    # 카테고리
    test_db.execute(text("""
        INSERT INTO categories (id, name, full_path) VALUES
        (1, '여행', '여행'),
        (2, '음식', '음식')
    """))

    # 클러스터
    test_db.execute(text("""
        INSERT INTO time_clusters (id, date, start_time, end_time, file_count, category_id) VALUES
        (1, '2023-04-15', '2023-04-15 10:00:00', '2023-04-15 12:30:00', 2, 1),
        (2, '2023-04-15', '2023-04-15 14:00:00', '2023-04-15 15:30:00', 1, 2),
        (3, '2023-04-16', '2023-04-16 09:00:00', '2023-04-16 10:00:00', 0, NULL)
    """))

    # 파일 (cluster_id로 클러스터 연결)
    test_db.execute(text("""
        INSERT INTO file_classifications (id, file_path, file_hash, extracted_date, cluster_id, status) VALUES
        (1, 'D:/Photos/img1.jpg', 'hash1', '2023-04-15 10:15:00', 1, 'pending'),
        (2, 'D:/Photos/img2.jpg', 'hash2', '2023-04-15 11:00:00', 1, 'pending'),
        (3, 'D:/Photos/img3.jpg', 'hash3', '2023-04-15 14:30:00', 2, 'pending')
    """))

    test_db.commit()


# ================================================
# Right: 기본 동작
# ================================================

def test_get_clusters_list_empty(client):
    """1.1 Right: GET /clusters → 빈 목록"""
    response = client.get("/api/ic/clusters")

    assert response.status_code == 200
    data = response.json()

    assert isinstance(data, list)
    assert len(data) == 0


def test_get_clusters_with_data(client, seeded_clusters):
    """1.2 Right: GET /clusters → 클러스터 목록"""
    response = client.get("/api/ic/clusters")

    assert response.status_code == 200
    data = response.json()

    assert isinstance(data, list)
    assert len(data) == 3

    # 모든 필드 존재 확인
    cluster = data[0]
    assert "cluster_id" in cluster
    assert "start_time" in cluster
    assert "end_time" in cluster
    assert "file_count" in cluster
    assert "duration_minutes" in cluster
    assert "category_path" in cluster


def test_get_clusters_duration_calculated(client, seeded_clusters):
    """1.3 Right: duration_minutes가 start/end_time 차이로 계산됨"""
    response = client.get("/api/ic/clusters")

    assert response.status_code == 200
    data = response.json()

    # 클러스터 1: 10:00 → 12:30 = 150분
    cluster1 = next(c for c in data if c["cluster_id"] == 1)
    assert cluster1["duration_minutes"] == 150

    # 클러스터 2: 14:00 → 15:30 = 90분
    cluster2 = next(c for c in data if c["cluster_id"] == 2)
    assert cluster2["duration_minutes"] == 90

    # 클러스터 3: 09:00 → 10:00 = 60분 (julianday 부동소수점으로 ±1 허용)
    cluster3 = next(c for c in data if c["cluster_id"] == 3)
    assert cluster3["duration_minutes"] in (59, 60)


def test_get_clusters_with_limit(client, seeded_clusters):
    """1.4 Right: GET /clusters?limit=2 → 제한"""
    response = client.get("/api/ic/clusters?limit=2")

    assert response.status_code == 200
    data = response.json()

    assert len(data) == 2


def test_get_cluster_detail(client, seeded_clusters):
    """1.5 Right: GET /clusters/{id} → 상세 조회"""
    response = client.get("/api/ic/clusters/1")

    assert response.status_code == 200
    data = response.json()

    assert data["cluster_id"] == 1
    assert data["file_count"] == 2
    assert data["duration_minutes"] == 150
    assert data["category_path"] == "여행"
    assert "files" in data
    assert isinstance(data["files"], list)


def test_get_cluster_detail_with_files(client, seeded_clusters):
    """1.6 Right: GET /clusters/{id} → 파일 목록 포함"""
    response = client.get("/api/ic/clusters/1")

    assert response.status_code == 200
    data = response.json()

    # 클러스터 1에 속한 파일 2개
    assert len(data["files"]) == 2

    # 파일 정보 확인
    file = data["files"][0]
    assert "file_id" in file
    assert "file_path" in file
    assert "capture_time" in file
    assert "thumbnail_url" in file


def test_get_cluster_files_ordered_by_time(client, seeded_clusters):
    """1.7 Right: 파일이 capture_time ASC 정렬"""
    response = client.get("/api/ic/clusters/1")

    assert response.status_code == 200
    files = response.json()["files"]

    # 10:15 < 11:00
    assert files[0]["file_id"] == 1
    assert files[1]["file_id"] == 2


# ================================================
# Boundary: 경계값 테스트
# ================================================

def test_get_cluster_nonexistent(client, seeded_clusters):
    """2.1 Boundary: GET /clusters/999 → 404"""
    response = client.get("/api/ic/clusters/999")

    assert response.status_code == 404
    assert "클러스터를 찾을 수 없습니다" in response.json()["detail"]


def test_get_clusters_limit_zero(client, seeded_clusters):
    """2.2 Boundary: GET /clusters?limit=0 → 빈 목록"""
    response = client.get("/api/ic/clusters?limit=0")

    assert response.status_code == 200
    data = response.json()

    assert len(data) == 0


def test_get_clusters_high_limit(client, seeded_clusters):
    """2.3 Boundary: GET /clusters?limit=1000 → 모든 클러스터"""
    response = client.get("/api/ic/clusters?limit=1000")

    assert response.status_code == 200
    data = response.json()

    assert len(data) == 3


def test_get_cluster_without_category(client, seeded_clusters):
    """2.4 Boundary: GET /clusters/3 → 카테고리 없는 클러스터"""
    response = client.get("/api/ic/clusters/3")

    assert response.status_code == 200
    data = response.json()

    assert data["cluster_id"] == 3
    assert data["category_path"] is None
    assert data["files"] == []  # 클러스터 3에는 파일 없음


def test_get_cluster_with_no_files(client, seeded_clusters):
    """2.5 Boundary: 파일이 없는 클러스터 → 빈 files 배열"""
    response = client.get("/api/ic/clusters/3")

    assert response.status_code == 200
    data = response.json()

    assert data["file_count"] == 0
    assert data["files"] == []


# ================================================
# Error: 오류 케이스
# ================================================

def test_get_cluster_invalid_id(client):
    """3.1 Error: GET /clusters/abc → 422"""
    response = client.get("/api/ic/clusters/abc")

    assert response.status_code == 422


def test_get_clusters_invalid_limit(client):
    """3.2 Error: GET /clusters?limit=abc → 422"""
    response = client.get("/api/ic/clusters?limit=abc")

    assert response.status_code == 422


def test_get_clusters_negative_limit(client, seeded_clusters):
    """3.3 Error: GET /clusters?limit=-1 → 빈 목록 or 에러"""
    response = client.get("/api/ic/clusters?limit=-1")

    assert response.status_code in [200, 422]


# ================================================
# CrossCheck: 교차 검증
# ================================================

def test_cluster_file_count_consistent(client, seeded_clusters):
    """4.1 CrossCheck: file_count와 실제 files 길이"""
    # 클러스터 1: file_count=2, 실제 파일 2개
    response = client.get("/api/ic/clusters/1")
    data = response.json()

    assert data["file_count"] == len(data["files"])


def test_run_clustering_all(client, test_db):
    """4.2 Right: POST /clusters/run?mode=all → 전체 재클러스터링"""
    from datetime import datetime, timedelta

    base_time = datetime(2023, 4, 15, 10, 0, 0)

    # 파일 3개 생성 (날짜 있음)
    for i in range(3):
        time = base_time + timedelta(minutes=i * 10)
        test_db.execute(text("""
            INSERT INTO file_classifications (id, file_path, file_hash, status, extracted_date)
            VALUES (:id, :path, 'hash', 'pending', :date)
        """), {"id": i+1, "path": f"/test/file{i+1}.jpg", "date": time.isoformat()})
    test_db.commit()

    response = client.post("/api/ic/clusters/run?mode=all&gap_minutes=60")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "started"
    assert data["mode"] == "all"


def test_run_clustering_invalid_mode(client):
    """4.3 Error: POST /clusters/run?mode=invalid → 400"""
    response = client.post("/api/ic/clusters/run?mode=invalid")
    assert response.status_code == 400


def test_run_clustering_status(client):
    """4.4 Right: GET /clusters/run/status → 상태 조회"""
    response = client.get("/api/ic/clusters/run/status")
    assert response.status_code == 200
    data = response.json()
    assert "is_running" in data
    assert "processed" in data
    assert "total" in data


def test_run_clustering_preserves_category(client, test_db):
    """4.5 CrossCheck: 재클러스터링 후 final_category_id 보존"""
    from datetime import datetime

    base_time = datetime(2023, 4, 15, 10, 0, 0)

    test_db.execute(text("INSERT INTO categories (id, name, full_path) VALUES (1, 'Travel', 'Travel')"))
    test_db.execute(text("""
        INSERT INTO file_classifications (id, file_path, file_hash, status, extracted_date, final_category_id)
        VALUES (1, '/test/file1.jpg', 'hash', 'ai_classified', :date, 1)
    """), {"date": base_time.isoformat()})
    test_db.commit()

    # 재클러스터링 트리거
    client.post("/api/ic/clusters/run?mode=all&gap_minutes=60")

    # 약간 대기 후 카테고리 보존 확인 (백그라운드 태스크이므로 직접 DB 확인)
    import time
    time.sleep(1)
    row = test_db.execute(text("SELECT final_category_id FROM file_classifications WHERE id = 1")).fetchone()
    assert row.final_category_id == 1


def test_cluster_ordering_by_start_time(client, seeded_clusters):
    """5.1 CrossCheck: 클러스터 목록이 start_time DESC 정렬"""
    response = client.get("/api/ic/clusters")

    assert response.status_code == 200
    data = response.json()

    start_times = [datetime.fromisoformat(c["start_time"]) for c in data]

    for i in range(len(start_times) - 1):
        assert start_times[i] >= start_times[i + 1], "클러스터가 내림차순 정렬되지 않음"
