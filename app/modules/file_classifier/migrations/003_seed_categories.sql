-- Phase 3: 카테고리 시드 데이터

-- 루트 카테고리
INSERT OR IGNORE INTO fc_categories (name, parent_id, full_path, sort_order) VALUES
('music', NULL, 'music', 10),
('video', NULL, 'video', 20),
('image', NULL, 'image', 30),
('archive', NULL, 'archive', 40),
('document', NULL, 'document', 50),
('installer', NULL, 'installer', 60),
('game', NULL, 'game', 70),
('misc', NULL, 'misc', 80);

-- music 하위
INSERT OR IGNORE INTO fc_categories (name, parent_id, full_path, sort_order) VALUES
('kpop', (SELECT id FROM fc_categories WHERE full_path='music'), 'music/kpop', 1),
('jpop', (SELECT id FROM fc_categories WHERE full_path='music'), 'music/jpop', 2),
('midi', (SELECT id FROM fc_categories WHERE full_path='music'), 'music/midi', 3),
('call_record', (SELECT id FROM fc_categories WHERE full_path='music'), 'music/call_record', 4),
('other', (SELECT id FROM fc_categories WHERE full_path='music'), 'music/other', 5);

-- video 하위
INSERT OR IGNORE INTO fc_categories (name, parent_id, full_path, sort_order) VALUES
('movie', (SELECT id FROM fc_categories WHERE full_path='video'), 'video/movie', 1),
('clip', (SELECT id FROM fc_categories WHERE full_path='video'), 'video/clip', 2),
('recording', (SELECT id FROM fc_categories WHERE full_path='video'), 'video/recording', 3),
('other', (SELECT id FROM fc_categories WHERE full_path='video'), 'video/other', 4);

-- image 하위
INSERT OR IGNORE INTO fc_categories (name, parent_id, full_path, sort_order) VALUES
('photo', (SELECT id FROM fc_categories WHERE full_path='image'), 'image/photo', 1),
('screenshot', (SELECT id FROM fc_categories WHERE full_path='image'), 'image/screenshot', 2),
('design', (SELECT id FROM fc_categories WHERE full_path='image'), 'image/design', 3),
('other', (SELECT id FROM fc_categories WHERE full_path='image'), 'image/other', 4);

-- archive 하위
INSERT OR IGNORE INTO fc_categories (name, parent_id, full_path, sort_order) VALUES
('installer', (SELECT id FROM fc_categories WHERE full_path='archive'), 'archive/installer', 1),
('document', (SELECT id FROM fc_categories WHERE full_path='archive'), 'archive/document', 2),
('source_code', (SELECT id FROM fc_categories WHERE full_path='archive'), 'archive/source_code', 3),
('unknown', (SELECT id FROM fc_categories WHERE full_path='archive'), 'archive/unknown', 4);

-- document 하위
INSERT OR IGNORE INTO fc_categories (name, parent_id, full_path, sort_order) VALUES
('pdf', (SELECT id FROM fc_categories WHERE full_path='document'), 'document/pdf', 1),
('office', (SELECT id FROM fc_categories WHERE full_path='document'), 'document/office', 2),
('text', (SELECT id FROM fc_categories WHERE full_path='document'), 'document/text', 3),
('calendar', (SELECT id FROM fc_categories WHERE full_path='document'), 'document/calendar', 4),
('other', (SELECT id FROM fc_categories WHERE full_path='document'), 'document/other', 5);

-- installer 하위
INSERT OR IGNORE INTO fc_categories (name, parent_id, full_path, sort_order) VALUES
('needed', (SELECT id FROM fc_categories WHERE full_path='installer'), 'installer/needed', 1),
('outdated', (SELECT id FROM fc_categories WHERE full_path='installer'), 'installer/outdated', 2),
('mobile', (SELECT id FROM fc_categories WHERE full_path='installer'), 'installer/mobile', 3),
('extension', (SELECT id FROM fc_categories WHERE full_path='installer'), 'installer/extension', 4),
('unknown', (SELECT id FROM fc_categories WHERE full_path='installer'), 'installer/unknown', 5);

-- game 하위
INSERT OR IGNORE INTO fc_categories (name, parent_id, full_path, sort_order) VALUES
('dtxmania', (SELECT id FROM fc_categories WHERE full_path='game'), 'game/dtxmania', 1),
('other', (SELECT id FROM fc_categories WHERE full_path='game'), 'game/other', 2);

-- misc 하위
INSERT OR IGNORE INTO fc_categories (name, parent_id, full_path, sort_order) VALUES
('build_artifact', (SELECT id FROM fc_categories WHERE full_path='misc'), 'misc/build_artifact', 1),
('log', (SELECT id FROM fc_categories WHERE full_path='misc'), 'misc/log', 2),
('temp', (SELECT id FROM fc_categories WHERE full_path='misc'), 'misc/temp', 3),
('torrent', (SELECT id FROM fc_categories WHERE full_path='misc'), 'misc/torrent', 4),
('unknown', (SELECT id FROM fc_categories WHERE full_path='misc'), 'misc/unknown', 5);
