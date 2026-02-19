"""통합 테스트 Scenario 5: 폴더 상속 + 일괄 매핑

카테고리 생성 → 상위 폴더 매핑 → 하위 폴더 상속
→ 모든 하위 파일 카테고리 적용 확인
"""
import pytest
from sqlalchemy import text


def test_folder_inherit_mapping_flow(test_db):
    """상위 폴더 매핑 → 하위 폴더 상속 → 파일 카테고리 적용"""

    # 1. 카테고리 생성
    test_db.execute(text(
        "INSERT INTO categories (id, name, full_path) VALUES (1, '여행', '여행')"
    ))

    # 2. 폴더 구조 생성 (상위 + 하위)
    test_db.execute(text("""
        INSERT INTO folder_mappings (id, folder_path, file_count, folder_status) VALUES
        (1, 'D:/Photos/여행', 0, 'clear'),
        (2, 'D:/Photos/여행/제주도', 5, 'clear'),
        (3, 'D:/Photos/여행/부산', 3, 'clear'),
        (4, 'D:/Photos/여행/제주도/해변', 2, 'clear')
    """))

    # 3. 파일 생성 (하위 폴더들에)
    files_data = [
        (1, "D:/Photos/여행/제주도/img1.jpg", 2),
        (2, "D:/Photos/여행/제주도/img2.jpg", 2),
        (3, "D:/Photos/여행/부산/img3.jpg", 3),
        (4, "D:/Photos/여행/부산/img4.jpg", 3),
        (5, "D:/Photos/여행/제주도/해변/img5.jpg", 4),
    ]
    for fid, path, folder_id in files_data:
        test_db.execute(text(
            "INSERT INTO file_classifications (id, file_path, file_hash, source_folder_id, status) "
            "VALUES (:id, :path, :hash, :fid, 'pending')"
        ), {"id": fid, "path": path, "hash": f"h{fid}", "fid": folder_id})
    test_db.commit()

    # 4. 상위 폴더에 카테고리 매핑
    test_db.execute(text(
        "UPDATE folder_mappings SET category_id = 1 WHERE id = 1"
    ))
    test_db.commit()

    # 5. 하위 폴더 상속 (folder_path LIKE 패턴)
    parent_path = "D:/Photos/여행"
    test_db.execute(text("""
        UPDATE folder_mappings SET category_id = 1
        WHERE folder_path LIKE :pattern AND category_id IS NULL
    """), {"pattern": f"{parent_path}%"})
    test_db.commit()

    # 6. 파일에 카테고리 적용
    test_db.execute(text("""
        UPDATE file_classifications SET
            final_category_id = (
                SELECT fm.category_id FROM folder_mappings fm
                WHERE fm.id = file_classifications.source_folder_id
            ),
            status = 'approved'
        WHERE EXISTS (
            SELECT 1 FROM folder_mappings fm
            WHERE fm.id = file_classifications.source_folder_id AND fm.category_id IS NOT NULL
        )
    """))
    test_db.commit()

    # 7. 검증
    # 모든 하위 폴더에 카테고리가 상속됨
    mapped = test_db.execute(text(
        "SELECT COUNT(*) FROM folder_mappings WHERE category_id = 1"
    )).scalar()
    assert mapped == 4  # 4개 폴더 모두

    # 모든 파일에 카테고리 적용됨
    approved = test_db.execute(text(
        "SELECT COUNT(*) FROM file_classifications WHERE final_category_id = 1 AND status = 'approved'"
    )).scalar()
    assert approved == 5  # 5개 파일 모두
