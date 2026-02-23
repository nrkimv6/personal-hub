-- Migration 102: notes/notes_archive 테이블에 메뉴/탭 연결 컬럼 추가
ALTER TABLE notes ADD COLUMN linked_menu_id TEXT;
ALTER TABLE notes ADD COLUMN linked_tab TEXT;
ALTER TABLE notes_archive ADD COLUMN linked_menu_id TEXT;
ALTER TABLE notes_archive ADD COLUMN linked_tab TEXT;
