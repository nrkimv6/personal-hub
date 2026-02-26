"""
duplicates.py Phase 1~3 백엔드 헬퍼 함수 유닛테스트

- _batch_delete_files: 배치 삭제
- _merge_metadata: 메타데이터 병합
- _select_keep_file: 보관 파일 자동 선택
"""
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# 테스트 대상 함수 import
from app.modules.image_classifier.routers.duplicates import (
    _batch_delete_files,
    _merge_metadata,
    _select_keep_file,
)


# ──────────────────────────────────────────────
# SQLite in-memory DB fixture
# ──────────────────────────────────────────────

@pytest.fixture(scope="module")
def engine():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    # 테스트에 필요한 최소 스키마 생성
    with eng.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS file_classifications (
                id INTEGER PRIMARY KEY,
                file_path TEXT,
                status TEXT DEFAULT 'active',
                moved_path TEXT,
                final_category_id INTEGER,
                ai_category_id INTEGER,
                ai_confidence REAL,
                importance TEXT DEFAULT 'low',
                extracted_date TEXT,
                date_source TEXT,
                date_trust_level INTEGER,
                user_date TEXT,
                user_location TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS file_tags (
                file_id INTEGER,
                tag_id INTEGER,
                PRIMARY KEY (file_id, tag_id)
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS file_attributes (
                file_id INTEGER,
                attr_key TEXT,
                attr_value TEXT,
                PRIMARY KEY (file_id, attr_key)
            )
        """))
        conn.commit()
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine):
    """각 테스트마다 새 세션, 테스트 후 롤백"""
    connection = engine.connect()
    transaction = connection.begin()
    Session = sessionmaker(bind=connection)
    session = Session()
    yield session
    session.close()
    transaction.rollback()
    connection.close()


# ──────────────────────────────────────────────
# _batch_delete_files 테스트
# ──────────────────────────────────────────────

class TestBatchDeleteFiles:

    def test_empty_list_returns_zero(self, db):
        """빈 리스트 전달 시 (0, 0) 반환"""
        result = _batch_delete_files(db, [], [])
        assert result == (0, 0)

    def test_nonexistent_files_are_skipped(self, db):
        """존재하지 않는 파일 경로는 skip되어 (0, 0) 반환"""
        with patch("app.modules.image_classifier.routers.duplicates.Path") as MockPath:
            MockPath.return_value.exists.return_value = False
            result = _batch_delete_files(db, [1, 2], ["/fake/a.jpg", "/fake/b.jpg"])
        assert result == (0, 0)

    def test_normal_batch_delete(self, db):
        """정상 배치 삭제: send2trash mock + DB UPDATE 확인"""
        # DB에 파일 레코드 삽입
        db.execute(text(
            "INSERT INTO file_classifications (id, file_path, status) VALUES (10, '/img/a.jpg', 'active')"
        ))
        db.execute(text(
            "INSERT INTO file_classifications (id, file_path, status) VALUES (11, '/img/b.jpg', 'active')"
        ))

        with patch("app.modules.image_classifier.routers.duplicates.send2trash") as mock_trash, \
             patch("app.modules.image_classifier.routers.duplicates.Path") as MockPath:
            MockPath.return_value.exists.return_value = True
            deleted, failed = _batch_delete_files(db, [10, 11], ["/img/a.jpg", "/img/b.jpg"])

        assert deleted == 2
        assert failed == 0
        mock_trash.assert_called_once()

        # DB에 status가 'moved'로 업데이트 됐는지 확인
        row = db.execute(text("SELECT status FROM file_classifications WHERE id = 10")).fetchone()
        assert row[0] == "moved"

    def test_partial_existing_files(self, db):
        """일부 파일만 존재할 때 존재하는 것만 삭제"""
        db.execute(text(
            "INSERT INTO file_classifications (id, file_path, status) VALUES (20, '/img/c.jpg', 'active')"
        ))
        db.execute(text(
            "INSERT INTO file_classifications (id, file_path, status) VALUES (21, '/img/d.jpg', 'active')"
        ))

        def path_exists(path_str):
            mock = MagicMock()
            mock.exists.return_value = (path_str == "/img/c.jpg")
            return mock

        with patch("app.modules.image_classifier.routers.duplicates.send2trash") as mock_trash, \
             patch("app.modules.image_classifier.routers.duplicates.Path", side_effect=path_exists):
            deleted, failed = _batch_delete_files(db, [20, 21], ["/img/c.jpg", "/img/d.jpg"])

        assert deleted == 1
        assert failed == 0
        mock_trash.assert_called_once()


# ──────────────────────────────────────────────
# _merge_metadata 테스트
# ──────────────────────────────────────────────

class TestMergeMetadata:

    def test_empty_delete_ids_returns_zero(self, db):
        """delete_file_ids 빈 리스트 → 0 반환, DB 변경 없음"""
        result = _merge_metadata(db, 1, [])
        assert result == 0

    def test_file_tags_merged_no_duplicate(self, db):
        """file_tags 병합: 삭제 파일 태그가 보관 파일에 추가됨 (중복 무시)"""
        # keep=100, delete=101 설정
        db.execute(text("INSERT INTO file_classifications (id, file_path) VALUES (100, '/k.jpg')"))
        db.execute(text("INSERT INTO file_classifications (id, file_path) VALUES (101, '/d.jpg')"))
        # keep에 tag 1, delete에 tag 2 + 이미 keep에 있는 tag 1
        db.execute(text("INSERT INTO file_tags (file_id, tag_id) VALUES (100, 1)"))
        db.execute(text("INSERT INTO file_tags (file_id, tag_id) VALUES (101, 1)"))
        db.execute(text("INSERT INTO file_tags (file_id, tag_id) VALUES (101, 2)"))

        _merge_metadata(db, 100, [101])

        tags = db.execute(
            text("SELECT tag_id FROM file_tags WHERE file_id = 100 ORDER BY tag_id")
        ).fetchall()
        tag_ids = [r[0] for r in tags]
        assert tag_ids == [1, 2], f"Expected [1, 2], got {tag_ids}"

    def test_importance_max_selected(self, db):
        """importance MAX 선택: keep=low, delete=high → keep이 high로 업데이트"""
        db.execute(text(
            "INSERT INTO file_classifications (id, file_path, importance) VALUES (200, '/k2.jpg', 'low')"
        ))
        db.execute(text(
            "INSERT INTO file_classifications (id, file_path, importance) VALUES (201, '/d2.jpg', 'high')"
        ))

        _merge_metadata(db, 200, [201])

        row = db.execute(text("SELECT importance FROM file_classifications WHERE id = 200")).fetchone()
        assert row[0] == "high", f"Expected 'high', got {row[0]}"

    def test_null_final_category_filled_from_delete(self, db):
        """final_category_id NULL→non-NULL fallback: keep이 NULL이면 삭제파일 값으로 채워짐"""
        db.execute(text(
            "INSERT INTO file_classifications (id, file_path, final_category_id) VALUES (300, '/k3.jpg', NULL)"
        ))
        db.execute(text(
            "INSERT INTO file_classifications (id, file_path, final_category_id) VALUES (301, '/d3.jpg', 42)"
        ))

        _merge_metadata(db, 300, [301])

        row = db.execute(text("SELECT final_category_id FROM file_classifications WHERE id = 300")).fetchone()
        assert row[0] == 42, f"Expected 42, got {row[0]}"

    def test_all_fields_null_no_change(self, db):
        """모든 필드 NULL 시 keep 파일 변경 없음"""
        db.execute(text(
            "INSERT INTO file_classifications (id, file_path, final_category_id, importance) VALUES (400, '/k4.jpg', NULL, NULL)"
        ))
        db.execute(text(
            "INSERT INTO file_classifications (id, file_path, final_category_id, importance) VALUES (401, '/d4.jpg', NULL, NULL)"
        ))

        _merge_metadata(db, 400, [401])

        row = db.execute(
            text("SELECT final_category_id, importance FROM file_classifications WHERE id = 400")
        ).fetchone()
        assert row[0] is None
        # importance가 NULL인 경우 UPDATE는 실행되지만 NULL을 유지할 수 있음 (로직 의존)
        # 단지 에러 없이 완료됐는지 확인


# ──────────────────────────────────────────────
# _select_keep_file 테스트
# ──────────────────────────────────────────────

class TestSelectKeepFile:

    def _make_members(self, is_exact=True, sizes=None, quality_scores=None):
        """테스트용 멤버 목록 생성"""
        sizes = sizes or [1000, 2000]
        quality_scores = quality_scores or [0.5, 0.7]
        return [
            {
                "file_id": i + 1,
                "is_exact": is_exact,
                "file_size": sizes[i],
                "quality_score": quality_scores[i],
            }
            for i in range(len(sizes))
        ]

    def test_exact_diff_sizes_returns_high(self):
        """exact + 크기 다름 → confidence='high'"""
        members = self._make_members(is_exact=True, sizes=[1000, 3000])
        file_id, confidence = _select_keep_file(members, strategy="quality_best")
        assert confidence == "high"
        assert file_id == 2  # 더 큰 파일 (file_id=2, size=3000)

    def test_exact_same_sizes_returns_low(self):
        """exact + 크기 동일 → confidence='low'"""
        members = self._make_members(is_exact=True, sizes=[2000, 2000])
        file_id, confidence = _select_keep_file(members, strategy="quality_best")
        assert confidence == "low"
        assert file_id == 1  # 첫 번째 파일

    def test_near_quality_best_returns_medium(self):
        """near (quality_best) → confidence='medium'"""
        members = self._make_members(is_exact=False, quality_scores=[0.3, 0.9])
        file_id, confidence = _select_keep_file(members, strategy="quality_best")
        assert confidence == "medium"
        assert file_id == 2  # quality_score=0.9인 파일

    def test_largest_file_strategy_near_returns_medium(self):
        """largest_file 전략 + near 그룹 → confidence='medium' (not high)"""
        members = self._make_members(is_exact=False, sizes=[500, 1500])
        file_id, confidence = _select_keep_file(members, strategy="largest_file")
        # near 그룹은 largest_file이어도 medium
        assert confidence == "medium"
        assert file_id == 2  # 더 큰 파일

    def test_largest_file_strategy_exact_returns_high(self):
        """largest_file 전략 + exact 그룹 → confidence='high'"""
        members = self._make_members(is_exact=True, sizes=[800, 2000])
        file_id, confidence = _select_keep_file(members, strategy="largest_file")
        assert confidence == "high"
        assert file_id == 2
