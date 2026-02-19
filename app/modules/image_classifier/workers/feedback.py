"""
피드백 학습 모듈

사용자 수정 이력을 학습하여 classification_rules 자동 생성
다음 배치 분류 시 반영
"""
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Dict, List
import json
import logging

logger = logging.getLogger(__name__)


class FeedbackLearner:
    """피드백 기반 학습"""

    def __init__(self, db: Session):
        self.db = db

    def record_correction(
        self,
        file_id: int,
        original_category_id: int,
        corrected_category_id: int,
    ):
        """
        사용자 수정 기록

        Args:
            file_id: 파일 ID
            original_category_id: 원래 AI가 분류한 카테고리
            corrected_category_id: 사용자가 수정한 카테고리
        """
        insert_query = text("""
            INSERT INTO feedback_history (file_id, original_category_id, corrected_category_id)
            VALUES (:file_id, :original_category_id, :corrected_category_id)
        """)
        self.db.execute(insert_query, {
            "file_id": file_id,
            "original_category_id": original_category_id,
            "corrected_category_id": corrected_category_id,
        })
        self.db.commit()

        logger.info(f"Feedback recorded: file={file_id}, {original_category_id} -> {corrected_category_id}")

    def analyze_feedback(self) -> List[Dict]:
        """
        피드백 분석 및 패턴 추출

        Returns:
            학습된 패턴 리스트
        """
        patterns = []

        # 1. 파일명 패턴 분석
        filename_patterns = self._analyze_filename_patterns()
        patterns.extend(filename_patterns)

        # 2. 폴더 경로 패턴 분석
        folder_patterns = self._analyze_folder_patterns()
        patterns.extend(folder_patterns)

        # 3. 키워드 패턴 분석
        keyword_patterns = self._analyze_keyword_patterns()
        patterns.extend(keyword_patterns)

        logger.info(f"Analyzed feedback: {len(patterns)} patterns found")

        return patterns

    def _analyze_filename_patterns(self) -> List[Dict]:
        """
        파일명 패턴 분석

        예: "영수증*.jpg" → shopping/receipt
        """
        query = text("""
            SELECT
                fc.file_path,
                fh.corrected_category_id,
                COUNT(*) as count
            FROM feedback_history fh
            JOIN file_classifications fc ON fh.file_id = fc.id
            GROUP BY fh.corrected_category_id, substr(fc.file_path, -20)
            HAVING count >= 3
        """)
        results = self.db.execute(query).fetchall()

        patterns = []
        for row in results:
            file_path = row.file_path
            category_id = row.corrected_category_id
            count = row.count

            # 파일명에서 패턴 추출 (간단한 휴리스틱)
            filename = file_path.split('/')[-1].split('\\')[-1]

            # 첫 단어를 패턴으로
            words = filename.replace('_', ' ').replace('-', ' ').split()
            if words:
                keyword = words[0]

                patterns.append({
                    "type": "filename",
                    "pattern": keyword,
                    "category_id": category_id,
                    "confidence": min(count / 10.0, 1.0),
                })

        return patterns

    def _analyze_folder_patterns(self) -> List[Dict]:
        """
        폴더 경로 패턴 분석

        예: "D:\\photos\\travel\\*" → outdoor/travel
        """
        query = text("""
            SELECT
                fc.file_path,
                fh.corrected_category_id,
                COUNT(*) as count
            FROM feedback_history fh
            JOIN file_classifications fc ON fh.file_id = fc.id
            GROUP BY fh.corrected_category_id
            HAVING count >= 5
        """)
        results = self.db.execute(query).fetchall()

        patterns = []
        for row in results:
            file_path = row.file_path
            category_id = row.corrected_category_id
            count = row.count

            # 폴더 경로 추출 (간단한 휴리스틱)
            parts = file_path.replace('\\', '/').split('/')
            if len(parts) >= 3:
                folder_hint = '/'.join(parts[-3:-1])  # 상위 2개 폴더

                patterns.append({
                    "type": "folder_path",
                    "pattern": folder_hint,
                    "category_id": category_id,
                    "confidence": min(count / 20.0, 1.0),
                })

        return patterns

    def _analyze_keyword_patterns(self) -> List[Dict]:
        """
        키워드 패턴 분석

        예: AI가 "screenshot"라고 판단했는데 사용자가 계속 "work" 카테고리로 수정 → 규칙 생성
        """
        query = text("""
            SELECT
                fh.original_category_id,
                fh.corrected_category_id,
                COUNT(*) as count
            FROM feedback_history fh
            GROUP BY fh.original_category_id, fh.corrected_category_id
            HAVING count >= 10
        """)
        results = self.db.execute(query).fetchall()

        patterns = []
        for row in results:
            original_id = row.original_category_id
            corrected_id = row.corrected_category_id
            count = row.count

            patterns.append({
                "type": "keyword",
                "pattern": f"ai_category:{original_id}",
                "category_id": corrected_id,
                "confidence": min(count / 50.0, 1.0),
            })

        return patterns

    def generate_rules(self, patterns: List[Dict]) -> int:
        """
        패턴을 classification_rules로 저장

        Args:
            patterns: 분석된 패턴 리스트

        Returns:
            생성된 규칙 수
        """
        count = 0

        for pattern in patterns:
            # 기존 규칙 확인
            check_query = text("""
                SELECT id FROM classification_rules
                WHERE rule_type = :rule_type
                  AND category_id = :category_id
                  AND rule_content = :rule_content
            """)
            existing = self.db.execute(check_query, {
                "rule_type": pattern["type"],
                "category_id": pattern["category_id"],
                "rule_content": pattern["pattern"],
            }).fetchone()

            if existing:
                continue  # 이미 있으면 스킵

            # 규칙 생성
            insert_query = text("""
                INSERT INTO classification_rules (
                    rule_type, category_id, rule_content, priority, source, is_active
                )
                VALUES (
                    :rule_type, :category_id, :rule_content, :priority, 'learned', 1
                )
            """)
            self.db.execute(insert_query, {
                "rule_type": pattern["type"],
                "category_id": pattern["category_id"],
                "rule_content": pattern["pattern"],
                "priority": int(pattern["confidence"] * 100),
            })
            count += 1

        self.db.commit()

        logger.info(f"Generated {count} new rules from feedback")

        return count

    def apply_rules(self, file_id: int, file_path: str) -> int:
        """
        학습된 규칙을 파일에 적용

        Args:
            file_id: 파일 ID
            file_path: 파일 경로

        Returns:
            매칭된 카테고리 ID (없으면 None)
        """
        # 우선순위 높은 규칙부터 조회
        query = text("""
            SELECT id, rule_type, category_id, rule_content, priority
            FROM classification_rules
            WHERE is_active = 1
            ORDER BY priority DESC, id
        """)
        rules = self.db.execute(query).fetchall()

        filename = file_path.split('/')[-1].split('\\')[-1]

        for rule in rules:
            rule_type = rule.rule_type
            category_id = rule.category_id
            pattern = rule.rule_content

            # 패턴 매칭
            matched = False

            if rule_type == "filename":
                if pattern.lower() in filename.lower():
                    matched = True
            elif rule_type == "folder_path":
                if pattern in file_path:
                    matched = True
            elif rule_type == "keyword":
                # "ai_category:123" 형태는 AI 분류 후 적용
                pass

            if matched:
                # 규칙 히트 카운트 증가
                update_query = text("""
                    UPDATE classification_rules
                    SET hit_count = hit_count + 1
                    WHERE id = :rule_id
                """)
                self.db.execute(update_query, {"rule_id": rule.id})
                self.db.commit()

                logger.info(f"Rule matched: file={file_id}, rule={rule.id}, category={category_id}")

                return category_id

        return None
