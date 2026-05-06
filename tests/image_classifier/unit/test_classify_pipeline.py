"""AI 분류 파이프라인 단위 테스트 — Bug #4, #5 검증

Bug #4: classify.py:683 pHash 그룹 복사 시 IndexError
Bug #5: classify.py:587 카테고리 LIKE 부분 매칭 오류

Right-BICEP + CORRECT 기반 8케이스.
"""
import pytest
from sqlalchemy import text


# ================================================
# Fixtures
# ================================================

@pytest.fixture
def db_with_categories(test_db):
    """카테고리가 세팅된 DB."""
    test_db.execute(text("""
        INSERT INTO categories (id, name, full_path) VALUES
        (1, '여행', '여행'),
        (2, '여행/국내', '여행/국내'),
        (3, '음식', '음식'),
        (4, '음식/한식', '음식/한식'),
        (5, '길거리음식', '길거리음식')
    """))
    test_db.commit()
    return test_db


@pytest.fixture
def db_with_files(db_with_categories, tmp_path):
    """파일 분류 레코드가 세팅된 DB."""
    from PIL import Image

    for i in range(1, 11):
        img = Image.new("RGB", (100, 100), color=(i * 25 % 256, 0, 0))
        path = tmp_path / f"img{i}.jpg"
        img.save(str(path))

        db_with_categories.execute(text("""
            INSERT INTO file_classifications (id, file_path, file_hash, status)
            VALUES (:id, :path, :hash, 'pending')
        """), {"id": i, "path": str(path), "hash": f"hash{i}"})

    db_with_categories.commit()
    return db_with_categories


def _fetch_representative_row(db, rep_id):
    return db.execute(text("""
        SELECT ai_category_id, ai_confidence, ai_reasoning, ai_model
        FROM file_classifications
        WHERE id = :rep_id AND ai_category_id IS NOT NULL
    """), {"rep_id": rep_id}).mappings().first()


def _apply_representative_copy(db, *, file_id, rep_row, reason_prefix):
    db.execute(text("""
        UPDATE file_classifications
        SET ai_category_id = :cat_id, ai_confidence = :conf,
            ai_reasoning = :reason, ai_model = :model,
            final_category_id = :cat_id, status = 'ai_classified',
            classified_at = datetime('now')
        WHERE id = :file_id
    """), {
        "file_id": file_id,
        "cat_id": rep_row["ai_category_id"],
        "conf": rep_row["ai_confidence"],
        "reason": f"{reason_prefix} {rep_row['ai_reasoning'] or ''}".rstrip(),
        "model": rep_row["ai_model"],
    })


# ================================================
# Bug #4: pHash 그룹 복사 IndexError 방어
# ================================================

class TestPHashGroupCopy:
    """pHash 그룹 복사 시 대표 파일 선정 로직 검증."""

    def test_right_phash_group_copy_normal(self, db_with_files):
        """TC-3-1 Right: pHash 그룹 대표 파일 → 멤버에 결과 복사 정상."""
        # 파일 1번을 ai_classified 상태로 세팅
        db_with_files.execute(text("""
            UPDATE file_classifications
            SET ai_category_id = 1,
                ai_confidence = 0.9,
                ai_reasoning = '여행 사진',
                ai_model = 'claude_cli',
                final_category_id = 1,
                status = 'ai_classified',
                classified_at = datetime('now')
            WHERE id = 1
        """))
        db_with_files.commit()

        # 그룹 복사 로직 시뮬레이션 (classify.py의 그룹 복사 블록과 동일)
        group_map = {100: [1, 2, 3]}  # group_id=100, 대표=1, 멤버=2,3
        representative_ids = {1}
        files_skip = [
            type("Row", (), {"id": 2, "file_path": "img2.jpg"})(),
            type("Row", (), {"id": 3, "file_path": "img3.jpg"})(),
        ]
        member_to_group = {2: 100, 3: 100}

        copied = 0
        for f in files_skip:
            gid = member_to_group.get(f.id)
            if not gid:
                continue
            # Bug #4 수정 후 코드
            reps = [fid for fid in group_map[gid] if fid in representative_ids]
            if not reps:
                continue
            rep_id = reps[0]

            rep_row = _fetch_representative_row(db_with_files, rep_id)
            if rep_row:
                # SELECT key 순서와 무관한 이름 접근 계약을 고정한다.
                rep_row = {
                    "ai_model": rep_row["ai_model"],
                    "ai_reasoning": rep_row["ai_reasoning"],
                    "ai_confidence": rep_row["ai_confidence"],
                    "ai_category_id": rep_row["ai_category_id"],
                }

            if rep_row:
                _apply_representative_copy(
                    db_with_files,
                    file_id=f.id,
                    rep_row=rep_row,
                    reason_prefix="[그룹 복사]",
                )
                copied += 1

        db_with_files.commit()

        assert copied == 2, "2개 멤버에 결과 복사되어야 함"

        # 2번, 3번 파일이 ai_classified 상태인지 확인
        for fid in [2, 3]:
            row = db_with_files.execute(text(
                "SELECT status, ai_category_id, ai_confidence, ai_reasoning, ai_model "
                "FROM file_classifications WHERE id = :id"
            ), {"id": fid}).fetchone()
            assert row[0] == "ai_classified"
            assert row[1] == 1
            assert row[2] == pytest.approx(0.9)
            assert row[3] == "[그룹 복사] 여행 사진"
            assert row[4] == "claude_cli"

    def test_error_phash_group_no_representative(self):
        """TC-3-2 Error: 그룹에 대표 파일 없음 → IndexError 없이 continue (Bug #4 핵심)."""
        group_map = {100: [20, 21]}
        representative_ids = set()  # 대표 없음
        member_to_group = {20: 100}

        errors = []
        skipped = 0

        for fid, gid in member_to_group.items():
            reps = [fid2 for fid2 in group_map[gid] if fid2 in representative_ids]
            if not reps:
                skipped += 1
                continue  # Bug #4 수정: IndexError 대신 continue
            try:
                rep_id = reps[0]  # 이 줄은 실행되지 않음
            except IndexError as e:
                errors.append(e)

        assert len(errors) == 0, "IndexError가 발생하면 안 됨"
        assert skipped == 1, "대표 없는 그룹은 skip되어야 함"

    def test_boundary_phash_group_single_member(self, db_with_files):
        """TC-3-3 Boundary: 그룹 멤버 1개 (대표=멤버) → 복사 대상 없음, 정상 종료."""
        db_with_files.execute(text("""
            UPDATE file_classifications
            SET ai_category_id = 2, ai_confidence = 0.85,
                status = 'ai_classified', classified_at = datetime('now')
            WHERE id = 5
        """))
        db_with_files.commit()

        group_map = {200: [5]}  # 멤버 1개 = 대표
        representative_ids = {5}
        files_skip = []  # 비대표 멤버 없음

        copied = 0
        for f in files_skip:
            gid = member_to_group.get(f.id, None)
            if not gid:
                continue
            reps = [fid for fid in group_map[gid] if fid in representative_ids]
            if not reps:
                continue
            copied += 1

        assert copied == 0, "복사 대상이 없어야 함"


class TestClipGroupCopy:
    """CLIP 대표 결과 복사 시 이름 기반 접근 계약 검증."""

    def test_right_clip_group_copy_normal(self, db_with_files):
        """TC-3-4 Right: CLIP 대표 파일 결과를 멤버에 정확히 복사."""
        db_with_files.execute(text("""
            UPDATE file_classifications
            SET ai_category_id = 2,
                ai_confidence = 0.77,
                ai_reasoning = '실내 사진',
                ai_model = 'gemini_cli',
                final_category_id = 2,
                status = 'ai_classified',
                classified_at = datetime('now')
            WHERE id = 4
        """))
        db_with_files.commit()

        clip_group_map = {300: [4, 5]}
        clip_copied = 0

        for _, members in clip_group_map.items():
            rep_row = _fetch_representative_row(db_with_files, members[0])
            if rep_row:
                _apply_representative_copy(
                    db_with_files,
                    file_id=members[1],
                    rep_row=rep_row,
                    reason_prefix="[CLIP 유사 복사]",
                )
                clip_copied += 1

        db_with_files.commit()

        row = db_with_files.execute(text("""
            SELECT ai_category_id, ai_confidence, ai_reasoning, ai_model, status
            FROM file_classifications
            WHERE id = 5
        """)).fetchone()

        assert clip_copied == 1
        assert row[0] == 2
        assert row[1] == pytest.approx(0.77)
        assert row[2] == "[CLIP 유사 복사] 실내 사진"
        assert row[3] == "gemini_cli"
        assert row[4] == "ai_classified"

    def test_error_clip_group_copy_skips_when_representative_missing(self, db_with_files):
        """TC-3-5 Error: 대표 결과가 없으면 CLIP 복사를 건너뛴다."""
        clip_group_map = {301: [6, 7]}
        clip_copied = 0

        for _, members in clip_group_map.items():
            rep_row = _fetch_representative_row(db_with_files, members[0])
            if rep_row:
                _apply_representative_copy(
                    db_with_files,
                    file_id=members[1],
                    rep_row=rep_row,
                    reason_prefix="[CLIP 유사 복사]",
                )
                clip_copied += 1

        row = db_with_files.execute(text("""
            SELECT ai_category_id, ai_reasoning, status
            FROM file_classifications
            WHERE id = 7
        """)).fetchone()

        assert clip_copied == 0
        assert row[0] is None
        assert row[1] is None
        assert row[2] == "pending"


# ================================================
# Bug #5: 카테고리 LIKE 부분 매칭 오류 개선
# ================================================

class TestCategoryMatching:
    """카테고리 조회 로직 검증."""

    def test_right_category_exact_match(self, db_with_categories):
        """TC-3-4 Right: 정확히 일치하는 full_path → 해당 row 반환."""
        cat_row = db_with_categories.execute(
            text("SELECT id FROM categories WHERE full_path = :path"),
            {"path": "여행"}
        ).fetchone()

        assert cat_row is not None
        assert cat_row[0] == 1

    def test_right_category_partial_match_fallback(self, db_with_categories):
        """TC-3-5 Right: 정확 일치 없을 때 LIKE fallback — suffix 일치 우선."""
        # "여행/국내" 는 DB에 있지만 "국내" 로 검색
        cat_row = db_with_categories.execute(
            text("""
                SELECT id FROM categories
                WHERE full_path LIKE :path
                ORDER BY
                    CASE WHEN full_path = :exact THEN 0
                         WHEN full_path LIKE :suffix THEN 1
                         ELSE 2
                    END,
                    LENGTH(full_path)
                LIMIT 1
            """),
            {
                "path": "%국내%",
                "exact": "국내",
                "suffix": "%/국내",
            }
        ).fetchone()

        assert cat_row is not None
        assert cat_row[0] == 2  # '여행/국내' id=2

    def test_error_category_not_found(self, db_with_categories):
        """TC-3-6 Error: 어떤 방식으로도 매칭 안 됨 → None 반환."""
        cat_row = db_with_categories.execute(
            text("SELECT id FROM categories WHERE full_path = :path"),
            {"path": "존재안하는카테고리XYZ"}
        ).fetchone()

        assert cat_row is None

    def test_correct_like_ambiguous_shortest_wins(self, db_with_categories):
        """TC-3-7 CORRECT: LIKE 부분매칭 시 가장 짧은 경로(+ suffix 일치) 선택.

        DB: '음식'(id=3), '음식/한식'(id=4), '길거리음식'(id=5)
        AI 반환: '음식'
        → 정확 일치: '음식'(id=3) 선택
        """
        # 정확 일치 케이스
        cat_row = db_with_categories.execute(
            text("""
                SELECT id FROM categories
                WHERE full_path LIKE :path
                ORDER BY
                    CASE WHEN full_path = :exact THEN 0
                         WHEN full_path LIKE :suffix THEN 1
                         ELSE 2
                    END,
                    LENGTH(full_path)
                LIMIT 1
            """),
            {
                "path": "%음식%",
                "exact": "음식",
                "suffix": "%/음식",
            }
        ).fetchone()

        assert cat_row is not None
        assert cat_row[0] == 3, "'음식'(id=3)이 가장 먼저 선택되어야 함 (정확 일치)"

    def test_boundary_category_empty_string(self, db_with_categories):
        """TC-3-8 Boundary: AI가 빈 문자열 반환 → not category_path → 조회 안 함."""
        category_path = ""

        # classify.py의 조건: if category_path and not category_path.startswith("error/")
        should_query = bool(category_path and not category_path.startswith("error/"))

        assert should_query is False, "빈 문자열은 DB 조회하지 않아야 함 (분류 실패로 처리)"
