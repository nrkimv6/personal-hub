"""통합 테스트 Scenario 1: 신규 사용자 전체 워크플로우

설정 저장 → 스캔 시작 → 스캔 완료 → 폴더 분류 → 카테고리 생성
→ 폴더 매핑 → 파일 카테고리 적용 → 파일 조회
"""
import pytest
from pathlib import Path
from PIL import Image
from sqlalchemy import text


@pytest.mark.asyncio
async def test_full_scan_classify_map_flow(test_db, tmp_path):
    """스캔 → 폴더 분류 → 카테고리 생성 → 매핑 → 파일 카테고리 적용"""
    from app.modules.image_classifier.workers.scanner import FolderScanner
    from app.modules.image_classifier.workers.folder_classifier import FolderClassifier

    # 1. 테스트 폴더 구조 생성
    img = Image.new("RGB", (100, 100), color="red")

    travel = tmp_path / "여행 2023"
    travel.mkdir()
    for i in range(3):
        img.save(str(travel / f"photo_{i}.jpg"))

    unknown = tmp_path / "새 폴더"
    unknown.mkdir()
    img.save(str(unknown / "a.jpg"))

    # 2. 스캔
    from app.modules.image_classifier.config import ImageClassifierSettings
    settings = ImageClassifierSettings()
    scanner = FolderScanner(db=test_db, settings=settings)
    await scanner.scan_folders([str(tmp_path)])

    assert scanner.total_files >= 4
    assert scanner.total_folders >= 2

    # DB에 폴더/파일이 저장되었는지 확인
    folders = test_db.execute(text("SELECT * FROM folder_mappings")).fetchall()
    files = test_db.execute(text("SELECT * FROM file_classifications")).fetchall()
    assert len(folders) >= 2
    assert len(files) >= 4

    # 3. 폴더 분류
    classifier = FolderClassifier(db=test_db)
    stats = classifier.classify_all_folders()

    assert stats["total"] >= 2
    # "여행 2023" → clear, "새 폴더" → unclear
    clear_count = test_db.execute(
        text("SELECT COUNT(*) FROM folder_mappings WHERE folder_status = 'clear'")
    ).scalar()
    unclear_count = test_db.execute(
        text("SELECT COUNT(*) FROM folder_mappings WHERE folder_status = 'unclear'")
    ).scalar()
    assert clear_count >= 1
    assert unclear_count >= 1

    # 4. 카테고리 생성
    test_db.execute(text(
        "INSERT INTO categories (name, full_path) VALUES ('여행', '여행')"
    ))
    test_db.commit()
    cat_id = test_db.execute(
        text("SELECT id FROM categories WHERE name = '여행'")
    ).scalar()

    # 5. 폴더 → 카테고리 매핑
    travel_folder = test_db.execute(
        text("SELECT id FROM folder_mappings WHERE folder_path LIKE '%여행%'")
    ).fetchone()
    test_db.execute(text(
        "UPDATE folder_mappings SET category_id = :cat_id WHERE id = :fid"
    ), {"cat_id": cat_id, "fid": travel_folder.id})
    test_db.commit()

    # 6. 파일에 카테고리 적용
    test_db.execute(text("""
        UPDATE file_classifications
        SET final_category_id = :cat_id, status = 'approved'
        WHERE source_folder_id = :fid
    """), {"cat_id": cat_id, "fid": travel_folder.id})
    test_db.commit()

    # 7. 검증: 파일 조회
    approved = test_db.execute(text(
        "SELECT COUNT(*) FROM file_classifications WHERE status = 'approved' AND final_category_id = :cid"
    ), {"cid": cat_id}).scalar()
    assert approved == 3
