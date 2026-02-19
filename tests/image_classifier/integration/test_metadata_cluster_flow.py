"""통합 테스트 Scenario 3: 메타데이터 추출 → 클러스터링 → 분류

스캔 완료 → 메타데이터 추출 (날짜) → 시간 클러스터링 (60분 gap)
→ 클러스터 조회 → 클러스터 분류 → 파일 상태 전환
"""
import pytest
from datetime import datetime, timedelta
from PIL import Image
from sqlalchemy import text


@pytest.mark.asyncio
async def test_metadata_extract_cluster_classify_flow(test_db, tmp_path):
    """메타데이터 추출 → 시간 클러스터링 → 클러스터 분류"""
    from app.modules.image_classifier.workers.metadata import MetadataExtractor
    from app.modules.image_classifier.workers.clustering import TimeClusteringWorker

    img = Image.new("RGB", (100, 100), color="blue")

    # 1. 시간대별 이미지 파일 생성 (파일명에 날짜 포함)
    folder = tmp_path / "photos"
    folder.mkdir()

    # 클러스터 A: 같은 시간대 (30분 간격)
    filenames_a = [
        "IMG_20230415_120000.jpg",  # 12:00
        "IMG_20230415_121500.jpg",  # 12:15
        "IMG_20230415_123000.jpg",  # 12:30
    ]
    # 클러스터 B: 다른 시간대 (2시간 후)
    filenames_b = [
        "IMG_20230415_140000.jpg",  # 14:00
        "IMG_20230415_141500.jpg",  # 14:15
    ]

    # 폴더 매핑 생성
    test_db.execute(text(
        "INSERT INTO folder_mappings (id, folder_path, file_count, folder_status) "
        "VALUES (1, :path, 5, 'clear')"
    ), {"path": str(folder)})

    all_filenames = filenames_a + filenames_b
    for i, fname in enumerate(all_filenames):
        path = folder / fname
        img.save(str(path))
        test_db.execute(text(
            "INSERT INTO file_classifications (id, file_path, file_hash, source_folder_id, status) "
            "VALUES (:id, :path, :hash, 1, 'pending')"
        ), {"id": i + 1, "path": str(path), "hash": f"hash_{i}"})
    test_db.commit()

    # 2. 메타데이터 추출
    extractor = MetadataExtractor(db=test_db)
    for i, fname in enumerate(all_filenames):
        path = folder / fname
        extractor.extract_and_save(i + 1, path)
    test_db.commit()

    # 날짜가 추출되었는지 확인
    dated = test_db.execute(text(
        "SELECT COUNT(*) FROM file_classifications WHERE extracted_date IS NOT NULL"
    )).scalar()
    assert dated == 5

    # 3. 시간 클러스터링
    clusterer = TimeClusteringWorker(db=test_db, gap_minutes=60)
    result = clusterer.cluster_all_unclassified()

    assert result["total"] == 5
    assert result["clusters"] == 2  # 2개 클러스터

    # 클러스터 확인
    clusters = test_db.execute(text(
        "SELECT * FROM time_clusters ORDER BY start_time"
    )).fetchall()
    assert len(clusters) == 2
    assert clusters[0].file_count == 3  # 클러스터 A
    assert clusters[1].file_count == 2  # 클러스터 B

    # 4. 카테고리 생성 및 클러스터 분류
    test_db.execute(text(
        "INSERT INTO categories (id, name, full_path) VALUES (1, '점심', '점심')"
    ))
    test_db.commit()

    clusterer.mark_cluster_classified(clusters[0].id, category_id=1)

    # 5. 검증: 파일 상태 전환
    classified = test_db.execute(text(
        "SELECT COUNT(*) FROM file_classifications "
        "WHERE final_category_id = 1 AND status = 'ai_classified'"
    )).scalar()
    assert classified == 3  # 클러스터 A의 3개 파일
