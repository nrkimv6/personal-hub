"""title 백필 마이그레이션 — plan_records 테이블의 title IS NULL 레코드 처리 (SQLite 전용 레거시).

⚠️ LEGACY: 이 스크립트는 SQLite data/monitor.db 직접 접근을 사용합니다.
   2026-04-10 PostgreSQL 전환 이후에는 data/monitor.db가 운영 DB가 아닙니다.
   DB 파일이 존재하지 않으면 스크립트가 종료됩니다.

동작:
  1. title IS NULL 레코드 조회
  2. file_path에서 # 헤더 파싱 → title UPDATE
  3. 파일이 존재하지 않으면 status='missing' 표시
"""

import re
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).parent.parent.parent / "data" / "monitor.db"


def extract_title_from_md(file_path: str) -> str | None:
    try:
        with open(file_path, encoding="utf-8", errors="replace") as f:
            first_line = f.readline().strip()
        if first_line.startswith("# "):
            return first_line[2:].strip()
    except Exception:
        pass
    return None


def run(db_path: str = str(DB_PATH)):
    if not Path(db_path).exists():
        print(f"❌ SQLite DB를 찾을 수 없습니다: {db_path}")
        print("이 스크립트는 SQLite 전용 레거시입니다. data/monitor.db가 없으면 실행하지 마세요.")
        sys.exit(1)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT id, file_path, status FROM plan_records WHERE title IS NULL")
    rows = cur.fetchall()
    print(f"title IS NULL 레코드: {len(rows)}건")

    updated = missing = 0
    for row in rows:
        record_id = row["id"]
        file_path = row["file_path"]
        current_status = row["status"]

        if not Path(file_path).exists():
            if current_status != "missing":
                cur.execute(
                    "UPDATE plan_records SET status='missing' WHERE id=?",
                    (record_id,),
                )
                missing += 1
            continue

        title = extract_title_from_md(file_path)
        if title:
            cur.execute(
                "UPDATE plan_records SET title=? WHERE id=?",
                (title, record_id),
            )
            updated += 1

    conn.commit()
    conn.close()
    print(f"완료 — title 갱신: {updated}건, missing 표시: {missing}건")


if __name__ == "__main__":
    run()
