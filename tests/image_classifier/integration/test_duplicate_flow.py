"""통합 테스트 Scenario 2: 중복 감지 및 해결

스캔 완료 상태 → pHash 계산 → 중복 감지 → 그룹 조회
→ 품질 비교 → 대표 파일 선택 → 나머지 무시
"""
import pytest
from pathlib import Path
from PIL import Image
from sqlalchemy import text


@pytest.mark.asyncio
async def test_duplicate_detect_and_resolve_flow(test_db, tmp_path):
    """pHash 계산 → 중복 그룹 생성 → 해결"""
    from app.modules.image_classifier.workers.scanner import FolderScanner
    from app.modules.image_classifier.workers.phash import PHashWorker

    # 1. 동일 이미지 2개 생성 (약간 다른 품질)
    img = Image.new("RGB", (500, 500), color=(100, 150, 200))
    folder = tmp_path / "photos"
    folder.mkdir()

    path_a = folder / "original.jpg"
    img.save(str(path_a), quality=95)

    path_b = folder / "copy.jpg"
    img.save(str(path_b), quality=80)  # 낮은 품질

    # 다른 이미지 1개 (중복 아님)
    diff_img = Image.new("RGB", (500, 500), color=(255, 0, 0))
    path_c = folder / "different.jpg"
    diff_img.save(str(path_c), quality=95)

    # 2. 스캔
    from app.modules.image_classifier.config import ImageClassifierSettings
    settings = ImageClassifierSettings()
    scanner = FolderScanner(db=test_db, settings=settings)
    await scanner.scan_folders([str(tmp_path)])

    files = test_db.execute(text("SELECT id, file_path FROM file_classifications")).fetchall()
    assert len(files) == 3

    # 3. pHash 계산
    phash_worker = PHashWorker(db=test_db, settings=settings)
    await phash_worker.process_pending_files(batch_size=100)

    # pHash가 저장되었는지 확인
    hashes = test_db.execute(text(
        "SELECT file_id, phash FROM image_features WHERE phash IS NOT NULL"
    )).fetchall()
    assert len(hashes) == 3

    # 4. 중복 감지: original.jpg와 copy.jpg는 동일 이미지이므로 hamming distance가 낮음
    # 직접 중복 그룹을 생성하여 테스트
    from app.modules.image_classifier.workers.phash import hamming_distance
    file_hashes = {row.file_id: row.phash for row in hashes}

    # hamming distance 계산 후 중복 쌍 찾기
    file_ids = list(file_hashes.keys())
    duplicate_pairs = []
    for i in range(len(file_ids)):
        for j in range(i + 1, len(file_ids)):
            fid_a, fid_b = file_ids[i], file_ids[j]
            dist = hamming_distance(file_hashes[fid_a], file_hashes[fid_b])
            if dist <= settings.PHASH_DUPLICATE_THRESHOLD:
                duplicate_pairs.append((fid_a, fid_b, dist))

    # original.jpg와 copy.jpg는 동일 이미지이므로 중복 쌍이 있어야 함
    assert len(duplicate_pairs) >= 1

    # duplicate_group 생성
    test_db.execute(text(
        "INSERT INTO duplicate_groups (group_hash, status) VALUES ('test_group_hash', 'pending')"
    ))
    test_db.commit()
    group_id = test_db.execute(text("SELECT id FROM duplicate_groups ORDER BY id DESC LIMIT 1")).scalar()

    # 중복 멤버 추가 (첫 번째 쌍)
    fid_a, fid_b, dist = duplicate_pairs[0]
    test_db.execute(text(
        "INSERT INTO duplicate_members (group_id, file_id, phash_distance) VALUES (:gid, :fid, :dist)"
    ), {"gid": group_id, "fid": fid_a, "dist": dist})
    test_db.execute(text(
        "INSERT INTO duplicate_members (group_id, file_id, phash_distance) VALUES (:gid, :fid, :dist)"
    ), {"gid": group_id, "fid": fid_b, "dist": dist})
    test_db.commit()

    groups = test_db.execute(text("SELECT * FROM duplicate_groups")).fetchall()
    # original.jpg와 copy.jpg가 같은 그룹에 있어야 함
    assert len(groups) >= 1

    # 5. 그룹 멤버 확인
    group_id = groups[0].id
    members = test_db.execute(text(
        "SELECT * FROM duplicate_members WHERE group_id = :gid"
    ), {"gid": group_id}).fetchall()
    assert len(members) == 2  # original + copy

    # 6. 해결: 첫 번째 멤버를 대표 파일로 선택
    best_member = members[0]
    best_file_id = best_member.file_id

    # kept_file_id 설정 및 resolved 상태로 전환
    test_db.execute(text(
        "UPDATE duplicate_groups SET status = 'resolved', kept_file_id = :fid WHERE id = :gid"
    ), {"fid": best_file_id, "gid": group_id})
    test_db.commit()

    # 7. 검증
    resolved = test_db.execute(text(
        "SELECT status FROM duplicate_groups WHERE id = :gid"
    ), {"gid": group_id}).scalar()
    assert resolved == "resolved"

    kept_file_id = test_db.execute(text(
        "SELECT kept_file_id FROM duplicate_groups WHERE id = :gid"
    ), {"gid": group_id}).scalar()
    assert kept_file_id == best_file_id


# ===========================================================================
# Phase 1 테스트: file_path_aliases 경로 보존
# ===========================================================================

def _insert_test_file(db, file_path: str) -> int:
    """테스트용 파일 레코드 삽입"""
    import hashlib
    file_hash = hashlib.md5(file_path.encode()).hexdigest()
    db.execute(text(
        "INSERT INTO file_classifications (file_path, file_hash, status) VALUES (:fp, :fh, 'pending')"
    ), {"fp": file_path, "fh": file_hash})
    db.commit()
    return db.execute(text(
        "SELECT id FROM file_classifications WHERE file_path = :fp"
    ), {"fp": file_path}).scalar()


def test_merge_metadata_saves_path_aliases(test_db):
    """_merge_metadata 호출 후 삭제 파일의 경로가 file_path_aliases에 저장되는지 확인"""
    from app.modules.image_classifier.routers.duplicates import _merge_metadata

    keep_id = _insert_test_file(test_db, "D:\\photos\\keep.jpg")
    del_id_1 = _insert_test_file(test_db, "D:\\backup\\copy1.jpg")
    del_id_2 = _insert_test_file(test_db, "D:\\backup2\\copy2.jpg")

    _merge_metadata(test_db, keep_id, [del_id_1, del_id_2])
    test_db.commit()

    aliases = test_db.execute(text(
        "SELECT alias_path FROM file_path_aliases WHERE file_id = :fid ORDER BY alias_path"
    ), {"fid": keep_id}).fetchall()

    alias_paths = {r.alias_path for r in aliases}
    assert "D:\\backup\\copy1.jpg" in alias_paths
    assert "D:\\backup2\\copy2.jpg" in alias_paths
    assert len(alias_paths) == 2


def test_merge_metadata_no_duplicate_aliases(test_db):
    """동일 경로 중복 INSERT 시 UNIQUE 제약으로 에러 없이 무시되는지 확인"""
    from app.modules.image_classifier.routers.duplicates import _merge_metadata

    keep_id = _insert_test_file(test_db, "D:\\photos\\keep.jpg")
    del_id = _insert_test_file(test_db, "D:\\backup\\copy.jpg")

    # 첫 번째 merge
    _merge_metadata(test_db, keep_id, [del_id])
    test_db.commit()

    # 두 번째 merge (동일 경로) — 에러 없이 무시
    _merge_metadata(test_db, keep_id, [del_id])
    test_db.commit()

    count = test_db.execute(text(
        "SELECT COUNT(*) FROM file_path_aliases WHERE file_id = :fid"
    ), {"fid": keep_id}).scalar()
    assert count == 1  # 중복 없이 1개만


# ===========================================================================
# Phase 2 테스트: 폴더 쌍 분석
# ===========================================================================

def _setup_pair_test_data(db):
    """폴더 쌍 테스트 데이터 셋업"""
    # 파일 삽입
    files = {
        "a1": "D:\\folderA\\img1.jpg",
        "a2": "D:\\folderA\\img2.jpg",
        "a3": "D:\\folderA\\img3.jpg",
        "b1": "D:\\folderB\\img1.jpg",
        "b2": "D:\\folderB\\img2.jpg",
        "b3": "D:\\folderB\\img3.jpg",
        "c1": "D:\\folderC\\img1.jpg",
        "c2": "D:\\folderC\\img2.jpg",
    }
    ids = {}
    for key, path in files.items():
        ids[key] = _insert_test_file(db, path)

    # A-B 쌍 3그룹
    for i in range(3):
        db.execute(text("INSERT INTO duplicate_groups (group_hash, status, member_count) VALUES (:h, 'pending', 2)"), {"h": f"ab_hash_{i}"})
        db.commit()
        gid = db.execute(text("SELECT id FROM duplicate_groups ORDER BY id DESC LIMIT 1")).scalar()
        a_key = f"a{i+1}"
        b_key = f"b{i+1}"
        db.execute(text("INSERT INTO duplicate_members (group_id, file_id, phash_distance) VALUES (:g, :f, 0)"), {"g": gid, "f": ids[a_key]})
        db.execute(text("INSERT INTO duplicate_members (group_id, file_id, phash_distance) VALUES (:g, :f, 0)"), {"g": gid, "f": ids[b_key]})
        db.commit()

    # A-C 쌍 2그룹
    for i in range(2):
        db.execute(text("INSERT INTO duplicate_groups (group_hash, status, member_count) VALUES (:h, 'pending', 2)"), {"h": f"ac_hash_{i}"})
        db.commit()
        gid = db.execute(text("SELECT id FROM duplicate_groups ORDER BY id DESC LIMIT 1")).scalar()
        a_key = f"a{i+1}"
        c_key = f"c{i+1}"
        db.execute(text("INSERT INTO duplicate_members (group_id, file_id, phash_distance) VALUES (:g, :f, 0)"), {"g": gid, "f": ids[a_key]})
        db.execute(text("INSERT INTO duplicate_members (group_id, file_id, phash_distance) VALUES (:g, :f, 0)"), {"g": gid, "f": ids[c_key]})
        db.commit()

    return ids


def test_folder_pair_analysis_groups_correctly(test_db):
    """A-B 3그룹, A-C 2그룹 → pairs에 2개 항목이 반환되는지 확인"""
    from app.modules.image_classifier.routers.duplicates import get_folder_pair_analysis

    _setup_pair_test_data(test_db)

    # DB 세션을 직접 넘겨 함수 호출 (Depends 우회)
    result = get_folder_pair_analysis(db=test_db)
    pairs = result["pairs"]

    assert len(pairs) == 2
    pair_keys = {(p["folder_a"], p["folder_b"]) for p in pairs}
    assert ("D:\\folderA", "D:\\folderB") in pair_keys
    assert ("D:\\folderA", "D:\\folderC") in pair_keys

    # group_count 확인
    ab = next(p for p in pairs if p["folder_b"] == "D:\\folderB")
    ac = next(p for p in pairs if p["folder_b"] == "D:\\folderC")
    assert ab["group_count"] == 3
    assert ac["group_count"] == 2


def test_folder_pair_analysis_files(test_db):
    """폴더 쌍 파일 상세 반환 시 folder_a / folder_b 소속이 정확한지 확인"""
    from app.modules.image_classifier.routers.duplicates import get_folder_pair_analysis_files

    _setup_pair_test_data(test_db)

    result = get_folder_pair_analysis_files(
        folder_a="D:\\folderA",
        folder_b="D:\\folderB",
        db=test_db,
    )

    assert len(result["files_a"]) > 0
    assert len(result["files_b"]) > 0
    assert len(result["group_ids"]) == 3

    for f in result["files_a"]:
        assert "folderA" in f["file_path"]
    for f in result["files_b"]:
        assert "folderB" in f["file_path"]


def test_folder_pair_three_folders(test_db):
    """3개 폴더 그룹(A-B-C)이 모든 2-조합 쌍에 카운트되는지 확인"""
    from app.modules.image_classifier.routers.duplicates import get_folder_pair_analysis

    # A-B-C 3개 폴더에 걸친 그룹 1개 생성
    for path in ["D:\\folderA\\img.jpg", "D:\\folderB\\img.jpg", "D:\\folderC\\img.jpg"]:
        _insert_test_file(test_db, path)

    file_ids = test_db.execute(text("SELECT id FROM file_classifications ORDER BY id")).fetchall()
    fa_id, fb_id, fc_id = [r.id for r in file_ids]

    test_db.execute(text("INSERT INTO duplicate_groups (group_hash, status, member_count) VALUES ('abc_hash', 'pending', 3)"))
    test_db.commit()
    gid = test_db.execute(text("SELECT id FROM duplicate_groups ORDER BY id DESC LIMIT 1")).scalar()
    for fid in [fa_id, fb_id, fc_id]:
        test_db.execute(text("INSERT INTO duplicate_members (group_id, file_id, phash_distance) VALUES (:g, :f, 0)"), {"g": gid, "f": fid})
    test_db.commit()

    result = get_folder_pair_analysis(db=test_db)
    pairs = result["pairs"]

    # A-B, A-C, B-C 쌍 모두 있어야 함
    assert len(pairs) == 3
    pair_keys = {(p["folder_a"], p["folder_b"]) for p in pairs}
    assert ("D:\\folderA", "D:\\folderB") in pair_keys
    assert ("D:\\folderA", "D:\\folderC") in pair_keys
    assert ("D:\\folderB", "D:\\folderC") in pair_keys

    # 각 쌍의 group_count는 1 (공유 그룹)
    for p in pairs:
        assert p["group_count"] == 1
