"""
API CORRECT TC
- Conformance: 응답 스키마 형식
- Ordering: 정렬 일관성
- Range: 파라미터 경계값
- Reference: 존재하지 않는 ID
- Existence: 빈 DB 응답
- Cardinality: 정확한 건수
- Time: 날짜 형식
"""
import pytest
import re

# SQLite는 'YYYY-MM-DD HH:MM:SS' 또는 ISO8601 'YYYY-MM-DDTHH:MM:SS' 형식을 모두 허용
ISO8601_PATTERN = re.compile(r'^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}')

class TestAPIConformance:
    """C-Conformance: 응답 스키마"""
    def test_files_response_schema(self, seeded_client):
        resp = seeded_client.get("/api/fc/files")
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "items" in data
        assert isinstance(data["total"], int)
        assert isinstance(data["items"], list)

    def test_stats_response_schema(self, seeded_client):
        resp = seeded_client.get("/api/fc/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_files" in data
        assert "by_group" in data
        assert "by_status" in data

    def test_health_response_schema(self, client):
        resp = client.get("/api/fc/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert data["status"] == "ok"

class TestAPIOrdering:
    """C-Ordering: 정렬 일관성"""
    def test_same_query_same_order(self, seeded_client):
        """동일 쿼리 2회 → 동일 순서"""
        resp1 = seeded_client.get("/api/fc/files")
        resp2 = seeded_client.get("/api/fc/files")
        ids1 = [item["id"] for item in resp1.json()["items"]]
        ids2 = [item["id"] for item in resp2.json()["items"]]
        assert ids1 == ids2

class TestAPIRange:
    """C-Range: 파라미터 경계값"""
    def test_page_size_1(self, seeded_client):
        """page_size=1 → 1개만 반환"""
        resp = seeded_client.get("/api/fc/files?page_size=1")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 1
        assert data["total"] == 6  # 전체는 6

    def test_page_out_of_range(self, seeded_client):
        """page 범위 초과 → 빈 items (400 또는 빈 결과)"""
        resp = seeded_client.get("/api/fc/files?page=9999&page_size=10")
        assert resp.status_code in (200, 400)
        if resp.status_code == 200:
            assert resp.json()["items"] == []

    def test_filter_nonexistent_group(self, seeded_client):
        """존재하지 않는 file_group 필터 → 0건"""
        resp = seeded_client.get("/api/fc/files?file_group=nonexistent")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

class TestAPIReference:
    """C-Reference: 존재하지 않는 ID"""
    def test_file_not_found_404(self, client):
        resp = client.get("/api/fc/files/99999")
        assert resp.status_code == 404

    def test_file_not_found_message(self, client):
        resp = client.get("/api/fc/files/99999")
        data = resp.json()
        assert "detail" in data or "error" in data

class TestAPIExistence:
    """C-Existence: 빈 DB"""
    def test_empty_stats_not_null(self, client):
        """빈 DB stats → null 아닌 0 반환"""
        resp = client.get("/api/fc/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("total_files") == 0
        assert data.get("by_group") is not None

    def test_empty_files_list(self, client):
        resp = client.get("/api/fc/files")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["items"] == []

class TestAPICardinality:
    """C-Cardinality: 정확한 건수"""
    def test_total_matches_seeded_count(self, seeded_client):
        """seeded_db 6건 → total == 6"""
        resp = seeded_client.get("/api/fc/files")
        assert resp.json()["total"] == 6

    def test_filter_reduces_count(self, seeded_client):
        """필터 적용 시 전체보다 작거나 같음"""
        total = seeded_client.get("/api/fc/files").json()["total"]
        filtered = seeded_client.get("/api/fc/files?file_group=music").json()["total"]
        assert filtered <= total

    def test_stats_by_group_sum(self, seeded_client):
        """by_group 합계 == total_files

        stats API의 by_group은 list[{file_group, count, total_size}] 형식
        """
        data = seeded_client.get("/api/fc/stats").json()
        total = data["total_files"]
        # by_group은 list of dict: [{file_group, count, total_size}, ...]
        group_sum = sum(item["count"] for item in data["by_group"])
        assert group_sum == total

class TestAPITime:
    """C-Time: 날짜 형식"""
    def test_file_dates_iso8601(self, seeded_client):
        """파일 날짜 필드 ISO8601 형식"""
        items = seeded_client.get("/api/fc/files").json()["items"]
        for item in items:
            if item.get("created_at"):
                assert ISO8601_PATTERN.match(item["created_at"]), \
                    f"created_at 형식 불일치: {item['created_at']}"
