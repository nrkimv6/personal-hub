"""통합 테스트 Scenario 4: 피드백 학습 → 규칙 자동 생성

AI 분류 완료 → 사용자 수정 (피드백) 10건+ → 패턴 분석
→ 규칙 자동 생성 → 새 파일에 규칙 적용 → 분류 정확도 향상
"""
import pytest
from sqlalchemy import text


def test_feedback_to_rule_generation_flow(test_db):
    """피드백 기록 → 패턴 분석 → 규칙 생성 → 규칙 적용"""
    from app.modules.image_classifier.workers.feedback import FeedbackLearner

    # 1. 카테고리 생성
    test_db.execute(text(
        "INSERT INTO categories (id, name, full_path) VALUES (1, '여행', '여행'), (2, '음식', '음식')"
    ))

    # 폴더 생성
    test_db.execute(text(
        "INSERT INTO folder_mappings (id, folder_path, file_count, folder_status) "
        "VALUES (1, 'D:/Photos/여행', 10, 'clear')"
    ))

    # 2. AI가 분류한 파일들 생성 (모두 '음식'으로 잘못 분류됨)
    for i in range(5):
        test_db.execute(text(
            "INSERT INTO file_classifications "
            "(id, file_path, file_hash, source_folder_id, ai_category_id, final_category_id, status) "
            "VALUES (:id, :path, :hash, 1, 2, 2, 'ai_classified')"
        ), {
            "id": i + 1,
            "path": f"D:/Photos/여행/travel_{i:03d}.jpg",
            "hash": f"hash_{i}",
        })
    test_db.commit()

    # 3. 사용자가 '여행'으로 수정 (피드백 기록)
    learner = FeedbackLearner(db=test_db)
    for i in range(5):
        learner.record_correction(
            file_id=i + 1,
            original_category_id=2,  # 음식 (AI가 분류)
            corrected_category_id=1,  # 여행 (사용자 수정)
        )
    test_db.commit()

    # 피드백 기록 확인
    fb_count = test_db.execute(text(
        "SELECT COUNT(*) FROM feedback_history"
    )).scalar()
    assert fb_count == 5

    # 4. 패턴 분석
    patterns = learner.analyze_feedback()
    assert len(patterns) > 0  # 최소 1개 패턴 발견

    # 5. 규칙 생성
    rule_count = learner.generate_rules(patterns)
    assert rule_count > 0

    rules = test_db.execute(text(
        "SELECT * FROM classification_rules WHERE source = 'learned'"
    )).fetchall()
    assert len(rules) > 0

    # 6. 새 파일에 규칙 적용
    test_db.execute(text(
        "INSERT INTO file_classifications "
        "(id, file_path, file_hash, source_folder_id, status) "
        "VALUES (100, 'D:/Photos/여행/travel_new.jpg', 'hash_new', 1, 'pending')"
    ))
    test_db.commit()

    matched_category = learner.apply_rules(
        file_id=100,
        file_path="D:/Photos/여행/travel_new.jpg"
    )

    # 규칙이 "여행" 카테고리를 매칭해야 함
    assert matched_category == 1  # 여행 카테고리
