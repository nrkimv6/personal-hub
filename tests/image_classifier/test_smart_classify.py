"""스마트 AI 분류 파이프라인 테스트 (RIGHT-BICEP)

Phase 1: auto_map_folders — 폴더 기반 자동 매핑
Phase 2: smart-start API — unclear 파일만 AI 분류 대상
"""
import pytest
from sqlalchemy import text


# ================================================
# Phase 1: FolderClassifier.auto_map_folders
# ================================================

class TestAutoMapFolders:
    """폴더 자동 매핑 테스트"""

    def _setup_categories(self, db):
        """테스트용 카테고리 생성 (실제 DB 스키마 매칭)"""
        db.execute(text("""
            INSERT OR IGNORE INTO categories (id, name, full_path) VALUES
            (100, 'travel', 'travel'),
            (101, 'food', 'food'),
            (102, 'capture', 'etc/capture'),
            (103, 'people', 'people'),
            (104, 'family', 'people/family'),
            (105, 'hobby', 'etc/hobby'),
            (106, 'work', 'work'),
            (107, 'documents', 'documents')
        """))
        db.commit()

    def _insert_folder(self, db, folder_path, status="unknown", category_id=None, file_count=5):
        """폴더 + 파일 삽입 헬퍼"""
        db.execute(text("""
            INSERT INTO folder_mappings (folder_path, folder_status, category_id, file_count)
            VALUES (:fp, :st, :cid, :fc)
        """), {"fp": folder_path, "st": status, "cid": category_id, "fc": file_count})
        db.commit()

        folder_id = db.execute(text(
            "SELECT id FROM folder_mappings WHERE folder_path = :fp"
        ), {"fp": folder_path}).fetchone().id

        # 파일 추가
        for i in range(file_count):
            db.execute(text("""
                INSERT INTO file_classifications (file_path, file_hash, source_folder_id, status)
                VALUES (:fp, :h, :fid, 'pending')
            """), {"fp": f"{folder_path}/img_{i}.jpg", "h": f"hash_{folder_id}_{i}", "fid": folder_id})
        db.commit()
        return folder_id

    # --- Right: 정상 동작 ---

    def test_clear_folder_mapped_to_category(self, test_db):
        """R: clear 폴더명(여행)이 travel 카테고리에 매핑됨"""
        self._setup_categories(test_db)
        self._insert_folder(test_db, "D:/Photos/여행사진", status="clear", file_count=3)

        from app.modules.image_classifier.workers.folder_classifier import FolderClassifier
        fc = FolderClassifier(test_db)
        result = fc.auto_map_folders()

        assert result["mapped"] >= 1
        assert result["files_mapped"] >= 3

        # 파일 상태 확인
        row = test_db.execute(text(
            "SELECT status, final_category_id FROM file_classifications WHERE file_path LIKE '%여행사진%' LIMIT 1"
        )).fetchone()
        assert row.status == "folder_mapped"
        assert row.final_category_id == 100  # travel

    def test_special_folder_foodie(self, test_db):
        """R: Foodie 특수 폴더가 food 카테고리에 매핑됨"""
        self._setup_categories(test_db)
        self._insert_folder(test_db, "D:/Photos/Foodie", status="clear", file_count=2)

        from app.modules.image_classifier.workers.folder_classifier import FolderClassifier
        fc = FolderClassifier(test_db)
        result = fc.auto_map_folders()

        assert result["files_mapped"] >= 2
        row = test_db.execute(text(
            "SELECT final_category_id FROM file_classifications WHERE file_path LIKE '%Foodie%' LIMIT 1"
        )).fetchone()
        assert row.final_category_id == 101  # food

    def test_special_folder_camera_not_mapped(self, test_db):
        """R: Camera 폴더는 내용 다양 → 매핑 안 됨 (None)"""
        self._setup_categories(test_db)
        self._insert_folder(test_db, "D:/DCIM/Camera", status="unclear", file_count=2)

        from app.modules.image_classifier.workers.folder_classifier import FolderClassifier
        fc = FolderClassifier(test_db)
        result = fc.auto_map_folders()

        # Camera는 SPECIAL_FOLDER_MAP에서 None → 매핑 안 됨
        row = test_db.execute(text(
            "SELECT final_category_id FROM file_classifications WHERE file_path LIKE '%Camera%' LIMIT 1"
        )).fetchone()
        assert row.final_category_id is None

    # --- Boundary: 경계 조건 ---

    def test_already_mapped_folder_skipped(self, test_db):
        """B: 이미 category_id가 있는 폴더는 건너뜀"""
        self._setup_categories(test_db)
        self._insert_folder(test_db, "D:/Photos/여행", status="clear", category_id=100, file_count=3)

        from app.modules.image_classifier.workers.folder_classifier import FolderClassifier
        fc = FolderClassifier(test_db)
        result = fc.auto_map_folders()

        assert result["mapped"] == 0  # 이미 매핑됨 → 건너뜀

    def test_no_matching_category_skipped(self, test_db):
        """B: 카테고리 테이블에 없는 패턴은 건너뜀"""
        # 카테고리 없이 폴더만 생성
        self._insert_folder(test_db, "D:/Photos/unknown_pattern_xyz", status="clear", file_count=1)

        from app.modules.image_classifier.workers.folder_classifier import FolderClassifier
        fc = FolderClassifier(test_db)
        result = fc.auto_map_folders()

        assert result["skipped"] >= 1

    def test_empty_db(self, test_db):
        """B: 폴더 없는 DB에서도 에러 없이 동작"""
        from app.modules.image_classifier.workers.folder_classifier import FolderClassifier
        fc = FolderClassifier(test_db)
        result = fc.auto_map_folders()

        assert result["mapped"] == 0
        assert result["skipped"] == 0
        assert result["files_mapped"] == 0

    # --- Cross-check: 교차 검증 ---

    def test_file_status_transitions(self, test_db):
        """C: pending → folder_mapped 전환 + final_category_id 설정"""
        self._setup_categories(test_db)
        fid = self._insert_folder(test_db, "D:/Photos/food_pics", status="clear", file_count=5)

        from app.modules.image_classifier.workers.folder_classifier import FolderClassifier
        fc = FolderClassifier(test_db)
        fc.auto_map_folders()

        # 모든 파일이 folder_mapped + final_category_id 설정됨
        rows = test_db.execute(text(
            "SELECT status, final_category_id FROM file_classifications WHERE source_folder_id = :fid"
        ), {"fid": fid}).fetchall()
        for row in rows:
            assert row.status == "folder_mapped"
            assert row.final_category_id == 101  # food

    # --- Error: 에러 조건 ---

    def test_classification_rules_integration(self, test_db):
        """E: classification_rules 테이블의 folder_path 규칙이 적용됨"""
        self._setup_categories(test_db)
        # 규칙 추가: "wedding" 패턴 → travel (임의)
        test_db.execute(text("""
            INSERT INTO classification_rules (rule_type, category_id, rule_content, priority, is_active)
            VALUES ('folder_path', 100, 'wedding_album', 10, 1)
        """))
        test_db.commit()

        self._insert_folder(test_db, "D:/Photos/wedding_album_2023", status="clear", file_count=2)

        from app.modules.image_classifier.workers.folder_classifier import FolderClassifier
        fc = FolderClassifier(test_db)
        result = fc.auto_map_folders()

        row = test_db.execute(text(
            "SELECT final_category_id FROM file_classifications WHERE file_path LIKE '%wedding_album%' LIMIT 1"
        )).fetchone()
        assert row.final_category_id == 100  # travel (규칙에 의해)


# ================================================
# Phase 2: smart-start API
# ================================================

class TestSmartStartAPI:
    """smart-start 엔드포인트 테스트"""

    def _setup_smart_test_data(self, db):
        """스마트 분류 테스트 데이터 준비"""
        # 카테고리
        db.execute(text("""
            INSERT OR IGNORE INTO categories (id, name, full_path) VALUES
            (100, 'travel', 'travel'),
            (101, 'food', 'food'),
            (102, 'capture', 'etc/capture')
        """))

        # clear 폴더 (auto-map 대상)
        db.execute(text("""
            INSERT INTO folder_mappings (id, folder_path, folder_status, file_count) VALUES
            (1, 'D:/Photos/여행사진', 'clear', 3)
        """))
        for i in range(3):
            db.execute(text("""
                INSERT INTO file_classifications (file_path, file_hash, source_folder_id, status)
                VALUES (:fp, :h, 1, 'pending')
            """), {"fp": f"D:/Photos/여행사진/img_{i}.jpg", "h": f"clear_{i}"})

        # unclear 폴더 (AI 분류 대상)
        db.execute(text("""
            INSERT INTO folder_mappings (id, folder_path, folder_status, file_count) VALUES
            (2, 'D:/Photos/새 폴더', 'unclear', 2)
        """))
        for i in range(2):
            db.execute(text("""
                INSERT INTO file_classifications (file_path, file_hash, source_folder_id, status)
                VALUES (:fp, :h, 2, 'pending')
            """), {"fp": f"D:/Photos/새 폴더/img_{i}.jpg", "h": f"unclear_{i}"})

        db.commit()

    def test_smart_start_filters_unclear_only(self, client, test_db):
        """R: smart-start는 unclear 파일만 AI 분류 대상으로 선별"""
        self._setup_smart_test_data(test_db)

        resp = client.post("/api/ic/classify/smart-start", json={"model": "claude_cli"})
        assert resp.status_code == 200
        data = resp.json()

        # clear 폴더 3건은 auto-map → AI 대상에서 제외
        # unclear 폴더 2건만 AI 대상
        assert data["total"] == 2
        assert "스마트 분류" in data["message"]

        # 분류 중지 (백그라운드 작업 정리)
        client.post("/api/ic/classify/stop")

    def test_smart_start_auto_maps_first(self, client, test_db):
        """R: smart-start가 먼저 auto-map을 실행함"""
        self._setup_smart_test_data(test_db)

        resp = client.post("/api/ic/classify/smart-start", json={"model": "claude_cli"})
        data = resp.json()

        # auto_map 결과가 메시지에 포함됨
        assert "폴더 매핑" in data["message"]

        client.post("/api/ic/classify/stop")

    def test_smart_start_status_has_phase(self, client, test_db):
        """R: status 응답에 phase/smart 필드 포함"""
        self._setup_smart_test_data(test_db)

        client.post("/api/ic/classify/smart-start", json={"model": "claude_cli"})
        resp = client.get("/api/ic/classify/status")
        data = resp.json()

        assert data.get("smart") is True
        assert "phase" in data

        client.post("/api/ic/classify/stop")

    def test_smart_start_all_mapped_no_ai(self, client, test_db):
        """B: 모든 파일이 auto-map되면 AI 대상 0건"""
        # 카테고리
        test_db.execute(text("""
            INSERT OR IGNORE INTO categories (id, name, full_path) VALUES
            (100, 'travel', 'travel')
        """))
        # clear 폴더만 (unclear 없음)
        test_db.execute(text("""
            INSERT INTO folder_mappings (id, folder_path, folder_status, file_count)
            VALUES (1, 'D:/Photos/travel_pics', 'clear', 2)
        """))
        for i in range(2):
            test_db.execute(text("""
                INSERT INTO file_classifications (file_path, file_hash, source_folder_id, status)
                VALUES (:fp, :h, 1, 'pending')
            """), {"fp": f"D:/Photos/travel_pics/img_{i}.jpg", "h": f"t_{i}"})
        test_db.commit()

        resp = client.post("/api/ic/classify/smart-start", json={"model": "claude_cli"})
        data = resp.json()

        assert data["total"] == 0
        assert data["status"] == "completed"

    def test_smart_start_blocks_duplicate(self, client, test_db):
        """E: 이미 실행 중이면 400 에러"""
        self._setup_smart_test_data(test_db)

        # classification_status를 수동으로 running 상태로 설정
        from app.modules.image_classifier.routers import classify
        original = classify.classification_status.copy()
        classify.classification_status["running"] = True

        try:
            resp = client.post("/api/ic/classify/smart-start", json={"model": "claude_cli"})
            assert resp.status_code == 400
            assert "already running" in resp.json()["detail"]
        finally:
            classify.classification_status.update(original)
