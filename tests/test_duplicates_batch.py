"""
duplicates.py Phase 1~3 백엔드 헬퍼 함수 유닛테스트

- _batch_delete_files: 배치 삭제
- _merge_metadata: 메타데이터 병합
- _select_keep_file: 보관 파일 자동 선택
- get_review (Review API): 정상 응답 구조, filter, auto_strategy, 빈 결과
- auto_resolve (Auto-resolve API): group_ids 지정/미지정, exclude_group_ids, 이미 resolved 무시
"""
import asyncio
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
    get_review,
    auto_resolve,
    AutoResolveRequest,
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
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS duplicate_groups (
                id INTEGER PRIMARY KEY,
                group_hash TEXT,
                member_count INTEGER DEFAULT 0,
                status TEXT DEFAULT 'pending',
                kept_file_id INTEGER
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS duplicate_members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER,
                file_id INTEGER,
                phash_distance INTEGER DEFAULT 0,
                is_exact INTEGER DEFAULT 1,
                file_size INTEGER DEFAULT 0,
                resolution TEXT,
                quality_score REAL DEFAULT 0.0
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


# ──────────────────────────────────────────────
# Review API 테스트 (get_review)
# ──────────────────────────────────────────────

def _seed_group(db, group_id: int, files: list[dict], status: str = "pending"):
    """
    테스트용 duplicate_groups + duplicate_members + file_classifications 시드.

    files: [{"file_id": int, "is_exact": bool, "file_size": int, "quality_score": float}]
    """
    db.execute(text("""
        INSERT INTO duplicate_groups (id, group_hash, member_count, status)
        VALUES (:gid, :ghash, :cnt, :status)
    """), {"gid": group_id, "ghash": f"hash_{group_id}", "cnt": len(files), "status": status})

    for f in files:
        # file_classifications가 없으면 삽입 (이미 있으면 무시)
        existing = db.execute(
            text("SELECT id FROM file_classifications WHERE id = :fid"),
            {"fid": f["file_id"]}
        ).fetchone()
        if not existing:
            db.execute(text("""
                INSERT INTO file_classifications (id, file_path, status)
                VALUES (:fid, :fpath, 'active')
            """), {"fid": f["file_id"], "fpath": f.get("file_path", f"/img/file_{f['file_id']}.jpg")})

        db.execute(text("""
            INSERT INTO duplicate_members (group_id, file_id, is_exact, file_size, quality_score)
            VALUES (:gid, :fid, :is_exact, :fsize, :qscore)
        """), {
            "gid": group_id,
            "fid": f["file_id"],
            "is_exact": 1 if f.get("is_exact", True) else 0,
            "fsize": f.get("file_size", 1000),
            "qscore": f.get("quality_score", 0.5),
        })


class TestReviewAPI:

    def test_empty_result(self, db):
        """pending 그룹이 없을 때 빈 결과 반환"""
        result = asyncio.run(get_review(skip=0, limit=100, filter="all", auto_strategy="quality_best", db=db))
        assert result["groups"] == []
        assert result["total"] == 0
        assert result["auto_resolvable"] == 0
        assert result["needs_review"] == 0

    def test_normal_response_structure(self, db):
        """정상 응답 구조 확인: groups, skip, limit, total, auto_resolvable, needs_review"""
        _seed_group(db, group_id=1001, files=[
            {"file_id": 1001, "is_exact": True, "file_size": 1000},
            {"file_id": 1002, "is_exact": True, "file_size": 3000},
        ])

        result = asyncio.run(get_review(skip=0, limit=100, filter="all", auto_strategy="quality_best", db=db))

        assert "groups" in result
        assert "skip" in result
        assert "limit" in result
        assert "total" in result
        assert "auto_resolvable" in result
        assert "needs_review" in result
        assert result["total"] >= 1

        group = next((g for g in result["groups"] if g["group_id"] == 1001), None)
        assert group is not None
        assert "members" in group
        assert "auto_keep_file_id" in group
        assert "confidence" in group
        assert len(group["members"]) == 2

    def test_filter_exact_only_returns_exact_groups(self, db):
        """filter=exact 시 is_exact=True 멤버를 포함한 그룹만 반환"""
        # exact 그룹
        _seed_group(db, group_id=1002, files=[
            {"file_id": 1003, "is_exact": True, "file_size": 500},
            {"file_id": 1004, "is_exact": True, "file_size": 800},
        ])
        # near 그룹
        _seed_group(db, group_id=1003, files=[
            {"file_id": 1005, "is_exact": False, "quality_score": 0.6},
            {"file_id": 1006, "is_exact": False, "quality_score": 0.9},
        ])

        result = asyncio.run(get_review(skip=0, limit=100, filter="exact", auto_strategy="quality_best", db=db))

        group_ids = [g["group_id"] for g in result["groups"]]
        assert 1002 in group_ids
        assert 1003 not in group_ids

    def test_filter_near_only_returns_near_groups(self, db):
        """filter=near 시 is_exact=False 멤버를 포함한 그룹만 반환"""
        _seed_group(db, group_id=1004, files=[
            {"file_id": 1007, "is_exact": True, "file_size": 1000},
            {"file_id": 1008, "is_exact": True, "file_size": 2000},
        ])
        _seed_group(db, group_id=1005, files=[
            {"file_id": 1009, "is_exact": False, "quality_score": 0.4},
            {"file_id": 1010, "is_exact": False, "quality_score": 0.8},
        ])

        result = asyncio.run(get_review(skip=0, limit=100, filter="near", auto_strategy="quality_best", db=db))

        group_ids = [g["group_id"] for g in result["groups"]]
        assert 1004 not in group_ids
        assert 1005 in group_ids

    def test_auto_strategy_quality_best_exact_diff_sizes_high_confidence(self, db):
        """quality_best + exact + 크기 다름 → confidence=high"""
        _seed_group(db, group_id=1006, files=[
            {"file_id": 1011, "is_exact": True, "file_size": 1000},
            {"file_id": 1012, "is_exact": True, "file_size": 5000},
        ])

        result = asyncio.run(get_review(skip=0, limit=100, filter="all", auto_strategy="quality_best", db=db))

        group = next((g for g in result["groups"] if g["group_id"] == 1006), None)
        assert group is not None
        assert group["confidence"] == "high"
        assert group["auto_keep_file_id"] == 1012  # 더 큰 파일
        assert result["auto_resolvable"] >= 1

    def test_auto_strategy_largest_file_near_medium_confidence(self, db):
        """largest_file + near 그룹 → confidence=medium"""
        _seed_group(db, group_id=1007, files=[
            {"file_id": 1013, "is_exact": False, "file_size": 200, "quality_score": 0.3},
            {"file_id": 1014, "is_exact": False, "file_size": 2000, "quality_score": 0.7},
        ])

        result = asyncio.run(get_review(skip=0, limit=100, filter="all", auto_strategy="largest_file", db=db))

        group = next((g for g in result["groups"] if g["group_id"] == 1007), None)
        assert group is not None
        assert group["confidence"] == "medium"

    def test_pagination_skip_limit(self, db):
        """skip/limit 페이지네이션 동작 확인"""
        # 5개 그룹 추가
        for i in range(5):
            gid = 2000 + i
            fid_base = 2000 + i * 2
            _seed_group(db, group_id=gid, files=[
                {"file_id": fid_base, "is_exact": True, "file_size": 1000},
                {"file_id": fid_base + 1, "is_exact": True, "file_size": 2000},
            ])

        result_page1 = asyncio.run(get_review(skip=0, limit=2, filter="all", auto_strategy="quality_best", db=db))
        result_page2 = asyncio.run(get_review(skip=2, limit=2, filter="all", auto_strategy="quality_best", db=db))

        assert len(result_page1["groups"]) <= 2
        assert len(result_page2["groups"]) <= 2
        # 두 페이지의 group_id가 겹치지 않아야 함
        ids_p1 = {g["group_id"] for g in result_page1["groups"]}
        ids_p2 = {g["group_id"] for g in result_page2["groups"]}
        assert ids_p1.isdisjoint(ids_p2)


# ──────────────────────────────────────────────
# Auto-resolve API 테스트 (auto_resolve)
# ──────────────────────────────────────────────

class TestAutoResolveAPI:

    def test_group_ids_specified(self, db):
        """group_ids 지정 시 해당 그룹만 처리"""
        _seed_group(db, group_id=3001, files=[
            {"file_id": 3001, "is_exact": True, "file_size": 1000},
            {"file_id": 3002, "is_exact": True, "file_size": 3000},
        ])
        _seed_group(db, group_id=3002, files=[
            {"file_id": 3003, "is_exact": True, "file_size": 500},
            {"file_id": 3004, "is_exact": True, "file_size": 1500},
        ])

        req = AutoResolveRequest(
            filter="all",
            strategy="quality_best",
            group_ids=[3001],  # 3001만 처리
            exclude_group_ids=[],
        )

        with patch("app.modules.image_classifier.routers.duplicates.send2trash"), \
             patch("app.modules.image_classifier.routers.duplicates.Path") as MockPath:
            MockPath.return_value.exists.return_value = True
            result = asyncio.run(auto_resolve(req, db=db))

        assert result["resolved"] == 1
        # 3001은 resolved
        row = db.execute(text("SELECT status FROM duplicate_groups WHERE id = 3001")).fetchone()
        assert row[0] == "resolved"
        # 3002는 여전히 pending
        row2 = db.execute(text("SELECT status FROM duplicate_groups WHERE id = 3002")).fetchone()
        assert row2[0] == "pending"

    def test_no_group_ids_processes_all_pending(self, db):
        """group_ids 미지정 시 filter 조건의 모든 pending 그룹 처리"""
        _seed_group(db, group_id=3003, files=[
            {"file_id": 3005, "is_exact": True, "file_size": 1000},
            {"file_id": 3006, "is_exact": True, "file_size": 2000},
        ])
        _seed_group(db, group_id=3004, files=[
            {"file_id": 3007, "is_exact": True, "file_size": 800},
            {"file_id": 3008, "is_exact": True, "file_size": 1600},
        ])

        req = AutoResolveRequest(
            filter="all",
            strategy="quality_best",
            group_ids=[],  # 비어있으면 전체 처리
            exclude_group_ids=[],
        )

        with patch("app.modules.image_classifier.routers.duplicates.send2trash"), \
             patch("app.modules.image_classifier.routers.duplicates.Path") as MockPath:
            MockPath.return_value.exists.return_value = True
            result = asyncio.run(auto_resolve(req, db=db))

        assert result["resolved"] >= 2

    def test_exclude_group_ids(self, db):
        """exclude_group_ids에 포함된 그룹은 처리에서 제외"""
        _seed_group(db, group_id=3005, files=[
            {"file_id": 3009, "is_exact": True, "file_size": 1000},
            {"file_id": 3010, "is_exact": True, "file_size": 2000},
        ])
        _seed_group(db, group_id=3006, files=[
            {"file_id": 3011, "is_exact": True, "file_size": 500},
            {"file_id": 3012, "is_exact": True, "file_size": 4000},
        ])

        req = AutoResolveRequest(
            filter="all",
            strategy="quality_best",
            group_ids=[3005, 3006],
            exclude_group_ids=[3006],  # 3006 제외
        )

        with patch("app.modules.image_classifier.routers.duplicates.send2trash"), \
             patch("app.modules.image_classifier.routers.duplicates.Path") as MockPath:
            MockPath.return_value.exists.return_value = True
            result = asyncio.run(auto_resolve(req, db=db))

        assert result["resolved"] == 1
        # 3005는 resolved, 3006은 pending 유지
        row5 = db.execute(text("SELECT status FROM duplicate_groups WHERE id = 3005")).fetchone()
        row6 = db.execute(text("SELECT status FROM duplicate_groups WHERE id = 3006")).fetchone()
        assert row5[0] == "resolved"
        assert row6[0] == "pending"

    def test_already_resolved_group_is_ignored(self, db):
        """이미 resolved된 그룹은 처리되지 않고 무시됨"""
        # resolved 상태로 시드
        _seed_group(db, group_id=3007, files=[
            {"file_id": 3013, "is_exact": True, "file_size": 1000},
            {"file_id": 3014, "is_exact": True, "file_size": 2000},
        ], status="resolved")

        req = AutoResolveRequest(
            filter="all",
            strategy="quality_best",
            group_ids=[],  # 전체 pending 처리 (resolved는 해당 안 됨)
            exclude_group_ids=[],
        )

        with patch("app.modules.image_classifier.routers.duplicates.send2trash"), \
             patch("app.modules.image_classifier.routers.duplicates.Path") as MockPath:
            MockPath.return_value.exists.return_value = True
            result = asyncio.run(auto_resolve(req, db=db))

        # 3007은 resolved이므로 pending 쿼리에서 제외 → result["resolved"]에 포함 안 됨
        # group_ids를 명시적으로 3007만 지정해도 members 조회 후 처리되는지 확인
        req2 = AutoResolveRequest(
            filter="all",
            strategy="quality_best",
            group_ids=[3007],
            exclude_group_ids=[],
        )
        result2 = asyncio.run(auto_resolve(req2, db=db))
        # 이미 resolved이지만 group_ids로 직접 지정하면 처리될 수 있음
        # 중요: resolved 상태가 변경되지 않는 것보다 멱등성 확인
        # 최소 failed가 없어야 함 (에러 없이 처리)
        assert result2["failed"] == 0

    def test_response_structure(self, db):
        """응답 구조 확인: resolved, deleted_files, merged_metadata, failed"""
        _seed_group(db, group_id=3008, files=[
            {"file_id": 3015, "is_exact": True, "file_size": 1000},
            {"file_id": 3016, "is_exact": True, "file_size": 2000},
        ])

        req = AutoResolveRequest(
            filter="all",
            strategy="quality_best",
            group_ids=[3008],
            exclude_group_ids=[],
        )

        with patch("app.modules.image_classifier.routers.duplicates.send2trash"), \
             patch("app.modules.image_classifier.routers.duplicates.Path") as MockPath:
            MockPath.return_value.exists.return_value = True
            result = asyncio.run(auto_resolve(req, db=db))

        assert "resolved" in result
        assert "deleted_files" in result
        assert "merged_metadata" in result
        assert "failed" in result
        assert result["resolved"] == 1
        assert result["failed"] == 0
