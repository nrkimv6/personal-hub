-- Phase 3: 기본 규칙 시드 데이터

-- 확장자 규칙
INSERT OR IGNORE INTO fc_rules (rule_type, category_id, rule_content, priority) VALUES
('extension', (SELECT id FROM fc_categories WHERE full_path='music/midi'), '{"value": ".mid"}', 100),
('extension', (SELECT id FROM fc_categories WHERE full_path='music/midi'), '{"value": ".midi"}', 100),
('extension', (SELECT id FROM fc_categories WHERE full_path='installer/mobile'), '{"value": ".apk"}', 100),
('extension', (SELECT id FROM fc_categories WHERE full_path='installer/mobile'), '{"value": ".ipa"}', 100),
('extension', (SELECT id FROM fc_categories WHERE full_path='installer/extension'), '{"value": ".vsix"}', 100),
('extension', (SELECT id FROM fc_categories WHERE full_path='document/calendar'), '{"value": ".ics"}', 100),
('extension', (SELECT id FROM fc_categories WHERE full_path='document/pdf'), '{"value": ".pdf"}', 100),
('extension', (SELECT id FROM fc_categories WHERE full_path='image/design'), '{"value": ".psd"}', 100),
('extension', (SELECT id FROM fc_categories WHERE full_path='misc/torrent'), '{"value": ".torrent"}', 100);

-- 파일명 패턴 규칙
INSERT OR IGNORE INTO fc_rules (rule_type, category_id, rule_content, priority) VALUES
('filename_pattern', (SELECT id FROM fc_categories WHERE full_path='music/call_record'), '{"pattern": "Record_.*\\.m4a"}', 90),
('filename_pattern', (SELECT id FROM fc_categories WHERE full_path='music/call_record'), '{"pattern": "통화녹음_.*"}', 90),
('filename_pattern', (SELECT id FROM fc_categories WHERE full_path='video/recording'), '{"pattern": "\\d{4}-\\d{2}-\\d{2}.*\\.(mp4|mkv|avi)"}', 80);

-- 메타데이터 규칙
INSERT OR IGNORE INTO fc_rules (rule_type, category_id, rule_content, priority) VALUES
('metadata_field', (SELECT id FROM fc_categories WHERE full_path='music/kpop'), '{"field": "artist_lang", "value": "ko"}', 70),
('metadata_field', (SELECT id FROM fc_categories WHERE full_path='music/jpop'), '{"field": "artist_lang", "value": "ja"}', 70);

-- 폴더 경로 규칙
INSERT OR IGNORE INTO fc_rules (rule_type, category_id, rule_content, priority) VALUES
('folder_path', (SELECT id FROM fc_categories WHERE full_path='game/dtxmania'), '{"pattern": "DTXMania"}', 60),
('folder_path', (SELECT id FROM fc_categories WHERE full_path='misc/build_artifact'), '{"pattern": "node_modules"}', 60);
