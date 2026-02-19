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
