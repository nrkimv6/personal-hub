"""
PostgreSQL SERIAL 시퀀스 즉시 동기화 스크립트.

앱 재시작 없이 현재 DB의 모든 SERIAL 시퀀스를 MAX(id)로 즉시 맞춥니다.

실행:
    python scripts/migrations/fix_pg_sequences.py
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

if __name__ == "__main__":
    from app.core.database import sync_serial_sequences
    synced = sync_serial_sequences()
    print(f"동기화 완료: {synced}개 시퀀스")
