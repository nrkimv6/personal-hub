"""파일 이동기 테스트"""
import shutil
import pytest
from pathlib import Path
from sqlalchemy import text


def _setup_move_test(test_db, tmp_path):
    """이동 테스트 기본 셋업"""
    # 카테고리 생성
    test_db.execute(text(
        "INSERT OR IGNORE INTO fc_categories (name, parent_id, full_path, sort_order) "
        "VALUES ('music', NULL, 'music', 10)"
    ))
    test_db.execute(text(
        "INSERT OR IGNORE INTO fc_categories (name, parent_id, full_path, sort_order) "
        "VALUES ('kpop', (SELECT id FROM fc_categories WHERE full_path='music'), 'music/kpop', 1)"
    ))
    test_db.commit()

    # 실제 파일 생성
    src_file = tmp_path / "test_song.mp3"
    src_file.write_bytes(b"fake mp3")

    cat_id = test_db.execute(text(
        "SELECT id FROM fc_categories WHERE full_path='music/kpop'"
    )).fetchone()[0]

    test_db.execute(text(
        "INSERT INTO fc_files (id, file_path, file_name, extension, file_size, file_group, status, final_category_id) "
        "VALUES (500, :path, 'test_song.mp3', '.mp3', 100, 'music', 'approved', :cat_id)"
    ), {"path": str(src_file), "cat_id": cat_id})
    test_db.commit()

    return str(src_file), cat_id


def test_preview(test_db, tmp_path, monkeypatch):
    """dry-run 미리보기"""
    from app.modules.file_classifier.workers.mover import MoveManager
    from app.modules.file_classifier import config

    src, cat_id = _setup_move_test(test_db, tmp_path)
    target_dir = tmp_path / "organized"
    monkeypatch.setattr(config.settings, "TARGET_ROOT_FOLDER", str(target_dir))

    manager = MoveManager(test_db)
    results = manager.preview()

    assert len(results) == 1
    assert results[0]["file_id"] == 500
    assert "music" in results[0]["destination"] and "kpop" in results[0]["destination"]
    # 파일은 아직 이동되지 않아야 함
    assert Path(src).exists()


def test_execute_move(test_db, tmp_path, monkeypatch):
    """실제 파일 이동"""
    from app.modules.file_classifier.workers.mover import MoveManager
    from app.modules.file_classifier import config

    src, cat_id = _setup_move_test(test_db, tmp_path)
    target_dir = tmp_path / "organized"
    monkeypatch.setattr(config.settings, "TARGET_ROOT_FOLDER", str(target_dir))

    manager = MoveManager(test_db)
    # 먼저 preview로 suggested_path 계산
    manager.preview()

    stats = manager.execute()
    assert stats["moved"] == 1
    assert stats["errors"] == 0

    # 파일이 이동됐는지 확인
    assert not Path(src).exists()

    row = test_db.execute(text(
        "SELECT status, moved_path FROM fc_files WHERE id = 500"
    )).fetchone()
    assert row[0] == 'moved'
    assert row[1] is not None
    assert Path(row[1]).exists()


def test_undo_move(test_db, tmp_path, monkeypatch):
    """이동 되돌리기"""
    from app.modules.file_classifier.workers.mover import MoveManager
    from app.modules.file_classifier import config

    src, cat_id = _setup_move_test(test_db, tmp_path)
    target_dir = tmp_path / "organized"
    monkeypatch.setattr(config.settings, "TARGET_ROOT_FOLDER", str(target_dir))

    manager = MoveManager(test_db)
    manager.preview()
    manager.execute()

    success = manager.undo(500)
    assert success is True
    assert Path(src).exists()

    row = test_db.execute(text("SELECT status FROM fc_files WHERE id = 500")).fetchone()
    assert row[0] == 'approved'


def test_preview_no_target_folder(test_db, monkeypatch):
    """TARGET_ROOT_FOLDER 없으면 빈 리스트"""
    from app.modules.file_classifier.workers.mover import MoveManager
    from app.modules.file_classifier import config

    monkeypatch.setattr(config.settings, "TARGET_ROOT_FOLDER", None)
    manager = MoveManager(test_db)
    results = manager.preview()
    assert results == []
