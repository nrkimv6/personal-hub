"""규칙 분류기 테스트"""
import json
import pytest
from sqlalchemy import text


def _seed_categories(db):
    """테스트용 카테고리 시드"""
    cats = [
        ('music', None, 'music', 10),
        ('music/kpop', None, 'music/kpop', 1),
        ('music/midi', None, 'music/midi', 3),
        ('misc', None, 'misc', 80),
        ('misc/torrent', None, 'misc/torrent', 4),
        ('document', None, 'document', 50),
        ('document/pdf', None, 'document/pdf', 1),
    ]
    for name, pid, fp, so in cats:
        db.execute(text(
            "INSERT OR IGNORE INTO fc_categories (name, parent_id, full_path, sort_order) VALUES (:n, :p, :fp, :s)"
        ), {"n": name.split('/')[-1], "p": pid, "fp": fp, "s": so})
    db.commit()


def _seed_rules(db):
    """테스트용 규칙 시드"""
    rules = [
        ('extension', 'misc/torrent', {"value": ".torrent"}, 100),
        ('extension', 'document/pdf', {"value": ".pdf"}, 100),
        ('extension', 'music/midi', {"value": ".mid"}, 100),
        ('metadata_field', 'music/kpop', {"field": "artist_lang", "value": "ko"}, 70),
    ]
    for rtype, cat_path, content, priority in rules:
        cat_id = db.execute(text("SELECT id FROM fc_categories WHERE full_path = :p"), {"p": cat_path}).fetchone()
        if cat_id:
            db.execute(text(
                "INSERT INTO fc_rules (rule_type, category_id, rule_content, priority) VALUES (:t, :c, :rc, :p)"
            ), {"t": rtype, "c": cat_id[0], "rc": json.dumps(content), "p": priority})
    db.commit()


def test_classify_by_extension(test_db):
    """확장자 기반 분류 테스트"""
    _seed_categories(test_db)
    _seed_rules(test_db)

    # 파일 삽입
    test_db.execute(text(
        "INSERT INTO fc_files (file_path, file_name, extension, file_size, file_group, status) "
        "VALUES ('/test/file.torrent', 'file.torrent', '.torrent', 1024, 'misc', 'pending')"
    ))
    test_db.commit()

    from app.modules.file_classifier.workers.rule_classifier import RuleClassifier
    classifier = RuleClassifier(test_db)
    stats = classifier.classify()

    assert stats["classified"] >= 1

    # 분류 결과 확인
    row = test_db.execute(text(
        "SELECT rule_category_id, status FROM fc_files WHERE file_name = 'file.torrent'"
    )).fetchone()
    assert row is not None
    assert row[1] == 'rule_classified'


def test_classify_by_metadata_field(test_db):
    """메타데이터 필드 기반 분류 테스트"""
    _seed_categories(test_db)
    _seed_rules(test_db)

    test_db.execute(text(
        "INSERT INTO fc_files (id, file_path, file_name, extension, file_size, file_group, status) "
        "VALUES (300, '/test/song.mp3', 'song.mp3', '.mp3', 5000, 'music', 'metadata_extracted')"
    ))
    test_db.execute(text(
        "INSERT INTO fc_music_meta (file_id, artist, artist_lang, has_tags) VALUES (300, '아이유', 'ko', 1)"
    ))
    test_db.commit()

    from app.modules.file_classifier.workers.rule_classifier import RuleClassifier
    classifier = RuleClassifier(test_db)
    stats = classifier.classify()

    row = test_db.execute(text(
        "SELECT rule_category_id, status FROM fc_files WHERE id = 300"
    )).fetchone()
    assert row is not None
    assert row[1] == 'rule_classified'


def test_classify_unmatched(test_db):
    """매칭 안 되는 파일 → unclassified"""
    _seed_categories(test_db)
    _seed_rules(test_db)

    test_db.execute(text(
        "INSERT INTO fc_files (file_path, file_name, extension, file_size, file_group, status) "
        "VALUES ('/test/unknown.xyz', 'unknown.xyz', '.xyz', 1024, 'misc', 'pending')"
    ))
    test_db.commit()

    from app.modules.file_classifier.workers.rule_classifier import RuleClassifier
    classifier = RuleClassifier(test_db)
    stats = classifier.classify()

    assert stats["unclassified"] >= 1
