"""
SQLite -> PostgreSQL 데이터 마이그레이션 스크립트.

실행:
    python scripts/migrate_sqlite_to_pg.py [--dry-run] [--sqlite-path /path/to/monitor.db]

옵션:
    --dry-run       실제 데이터 이관 없이 스키마 생성 + 행 수 집계만 수행
    --sqlite-path   SQLite DB 파일 경로 (기본값: {PROJECT_ROOT}/data/monitor.db)

전제조건:
    - .env에 DATABASE_URL=postgresql://... 설정
    - PostgreSQL 서버 실행 중, monitor DB/유저 존재
    - pip install psycopg2-binary sqlalchemy
"""

import sys
import os
import argparse
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

# 프로젝트 루트를 sys.path에 추가
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

# .env 로드 (존재할 경우)
try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from unittest.mock import patch

# ── 설정 ──────────────────────────────────────────────────────────────────

_DEFAULT_SQLITE_PATH = PROJECT_ROOT / "data" / "monitor.db"
CHUNK_SIZE = 1000

# 이관 제외 테이블 (미사용 + SQLite 내부)
EXCLUDED_TABLES = frozenset({
    "booking_history",
    "monitoring_logs",
    "conflict_resolutions",
    "remote_server_status",
    "sqlite_sequence",    # SQLite 내부 테이블
    "sqlite_stat1",       # SQLite 통계 테이블
})

# SERIAL 시퀀스 동기화 대상 — app.core.database.PG_SERIAL_TABLES가 단일 소스
from app.core.database import PG_SERIAL_TABLES as SERIAL_TABLES

WRITING_TABLES = (
    "writing_sources",
    "generated_writings",
    "writing_elements",
    "writing_rss_feeds",
    "writing_search_queries",
    "task_schedules",
    "task_schedule_runs",
)
# UUID PK 기반인 writing_collection_tasks는 SQLite legacy dump와의 직접 backfill 대상에서 제외한다.
WRITING_TABLE_SET = frozenset(WRITING_TABLES)
MIGRATION_PRIORITY = {
    "task_schedules": 10,
    "task_schedule_runs": 20,
}


def parse_selected_tables_arg(raw_tables: Optional[str]) -> Optional[List[str]]:
    """--tables 인자를 정규화한다."""
    if not raw_tables:
        return None
    tables = [part.strip() for part in raw_tables.split(",") if part.strip()]
    if not tables:
        return None
    # 중복 제거 + 입력 순서 유지
    return list(dict.fromkeys(tables))


def format_selected_tables(selected_tables: Optional[Sequence[str]]) -> str:
    """로그용 선택 테이블 문자열."""
    if not selected_tables:
        return "ALL"
    return ", ".join(selected_tables)


def order_tables_for_migration(tables: Sequence[str]) -> List[str]:
    """FK 의존성을 고려해 일부 테이블 순서를 보정한다."""
    indexed = list(enumerate(tables))
    ordered = sorted(
        indexed,
        key=lambda item: (MIGRATION_PRIORITY.get(item[1], 1000), item[0]),
    )
    return [table for _, table in ordered]


def build_startup_banner(
    sqlite_path: Path,
    sqlite_url: str,
    pg_url: str,
    selected_tables: Optional[Sequence[str]],
    dry_run: bool,
) -> str:
    """시작 로그 문자열 생성."""
    lines = [
        "=" * 60,
        "SQLite -> PostgreSQL 마이그레이션 시작",
        f"  SQLite path: {sqlite_path}",
        f"  소스: {sqlite_url}",
        f"  대상: {pg_url}",
        f"  테이블: {format_selected_tables(selected_tables)}",
    ]
    if dry_run:
        lines.append("  모드: DRY RUN (실제 이관 없음)")
    lines.append("=" * 60)
    return "\n".join(lines)


def get_pg_url() -> str:
    """환경변수에서 PG URL 읽기"""
    from app.core.config import settings
    url = settings.DATABASE_URL
    if not url.startswith("postgresql"):
        print(f"ERROR: DATABASE_URL이 PostgreSQL이 아닙니다: {url}")
        print("  .env 파일에 DATABASE_URL=postgresql://... 설정 필요")
        sys.exit(1)
    return url


def create_pg_schema(pg_engine) -> None:
    """PostgreSQL 스키마 생성 (ORM 모델 + init_extra_tables)"""
    print("\n[1단계] PostgreSQL 스키마 생성")

    # ORM 모델 테이블 생성
    import app.models  # noqa: F401 - 전체 모델 등록
    from app.models.base import Base as ModelBase

    # claude_worker 모듈 모델 추가 (llm_requests 테이블)
    try:
        from app.modules.claude_worker.models.llm_request import LLMRequest, LLMWorkerStatus  # noqa: F401
    except ImportError:
        print("  [경고] claude_worker LLMRequest 모델 로드 실패 (무시)")

    print("  ORM 모델 테이블 생성 중...")
    ModelBase.metadata.create_all(bind=pg_engine)
    print(f"  -> {len(ModelBase.metadata.tables)}개 ORM 테이블 처리")

    # init_extra_tables() 테이블 생성 (is_pg 패치)
    import app.core.database as db_mod
    PgSession = sessionmaker(autocommit=False, autoflush=False, bind=pg_engine)
    print("  init_extra_tables() 실행 중...")
    with patch.object(db_mod, "is_pg", True), \
         patch.object(db_mod, "is_sqlite", False), \
         patch.object(db_mod, "SessionLocal", PgSession):
        db_mod.init_extra_tables()
    print("  -> init_extra_tables() 완료")


def create_missing_tables_from_sqlite(sqlite_engine, pg_engine, missing: List[str]) -> None:
    """SQLite에 있지만 PG에 없는 테이블을 SQLAlchemy reflection으로 생성"""
    if not missing:
        return
    print(f"  SQLite reflection으로 {len(missing)}개 테이블 생성 중...")
    from sqlalchemy import Table, MetaData, Column
    from sqlalchemy import Integer, Float, Text, Boolean, DateTime, String

    SQLITE_TO_PG_TYPE = {
        "INTEGER": Integer(),
        "REAL": Float(),
        "TEXT": Text(),
        "BLOB": Text(),  # BLOB → TEXT (바이너리 데이터 없으면 TEXT로 충분)
        "NUMERIC": Float(),
        "BOOLEAN": Boolean(),
        "DATETIME": DateTime(),
        "TIMESTAMP": DateTime(),
        "VARCHAR": Text(),
    }

    sqlite_insp = inspect(sqlite_engine)
    pg_meta = MetaData()

    for table_name in missing:
        try:
            cols_info = sqlite_insp.get_columns(table_name)
            pk_info = sqlite_insp.get_pk_constraint(table_name)
            pk_cols = set(pk_info.get("constrained_columns", []))

            columns = []
            for col in cols_info:
                col_name = col["name"]
                raw_type = str(col["type"]).upper().split("(")[0].strip()
                pg_type = SQLITE_TO_PG_TYPE.get(raw_type, Text())
                is_pk = col_name in pk_cols
                nullable = not is_pk and col.get("nullable", True)
                column = Column(
                    col_name,
                    pg_type,
                    primary_key=is_pk,
                    nullable=nullable,
                    autoincrement=is_pk and raw_type == "INTEGER",
                )
                columns.append(column)

            tbl = Table(table_name, pg_meta, *columns)
            tbl.create(pg_engine, checkfirst=True)
            print(f"    [생성] {table_name}")
        except Exception as e:
            print(f"    [실패] {table_name}: {e}")


def get_pg_boolean_columns(pg_engine, table_name: str) -> set:
    """PG 테이블에서 BOOLEAN 타입 컬럼 목록 반환"""
    with pg_engine.connect() as conn:
        result = conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema=current_schema() AND table_name=:t AND data_type='boolean'"
        ), {"t": table_name})
        return {row[0] for row in result}


def get_sqlite_tables(
    sqlite_engine,
    selected_tables: Optional[Sequence[str]] = None,
) -> List[str]:
    """SQLite에서 이관 대상 테이블 목록 반환"""
    inspector = inspect(sqlite_engine)
    all_tables = inspector.get_table_names()
    migratable = [t for t in all_tables if t not in EXCLUDED_TABLES]
    if not selected_tables:
        return order_tables_for_migration(migratable)

    selected_set = set(selected_tables)
    missing_tables = [t for t in selected_tables if t not in all_tables]
    if missing_tables:
        raise ValueError(
            f"SQLite에 없는 테이블이 선택되었습니다: {', '.join(missing_tables)}"
        )

    ordered = [t for t in migratable if t in selected_set]
    return order_tables_for_migration(ordered)


def get_pg_tables(pg_engine) -> set:
    """PostgreSQL의 현재 테이블 목록 반환"""
    with pg_engine.connect() as conn:
        result = conn.execute(text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema=current_schema() AND table_type='BASE TABLE'"
        ))
        return {row[0] for row in result}


def migrate_table(
    sqlite_engine,
    pg_engine,
    table_name: str,
    dry_run: bool = False,
    allow_existing_rows: bool = False,
) -> Tuple[int, int]:
    """단일 테이블 데이터 이관. (이관 행 수, 실패 행 수) 반환"""
    migrated = 0
    failed = 0

    # SQLite 소스에서 행 수 확인
    with sqlite_engine.connect() as src:
        total = src.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar()

    if total == 0:
        return 0, 0

    if dry_run:
        return total, 0

    # PG에 이미 데이터가 있으면 기본적으로 스킵하되, 표적 backfill은 충돌 무시 모드로 계속 진행
    with pg_engine.connect() as dst:
        existing = dst.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar()
    if existing > 0 and not allow_existing_rows:
        print(f"  [건너뜀] {table_name}: PG에 이미 {existing}행 존재")
        return 0, 0
    if existing > 0 and allow_existing_rows:
        print(f"  [표적 backfill] {table_name}: PG에 기존 {existing}행 존재, ON CONFLICT DO NOTHING 모드로 진행")

    # 빈 문자열 → None 변환 대상 컬럼 사전 추출 (SQLite 기준)
    inspector = inspect(sqlite_engine)
    timestamp_cols = {
        col["name"]
        for col in inspector.get_columns(table_name)
        if "TIMESTAMP" in str(col["type"]).upper() or "DATE" in str(col["type"]).upper()
    }

    # PG boolean 컬럼 추출 (SQLite INTEGER → PG boolean 변환)
    boolean_cols = get_pg_boolean_columns(pg_engine, table_name)

    # PG 실제 컬럼 목록 (SQLite에만 있는 컬럼 필터링용)
    pg_inspector = inspect(pg_engine)
    pg_cols = {col["name"] for col in pg_inspector.get_columns(table_name)}

    offset = 0
    while offset < total:
        with sqlite_engine.connect() as src:
            rows = src.execute(
                text(f"SELECT * FROM {table_name} LIMIT {CHUNK_SIZE} OFFSET {offset}")
            ).mappings().all()

        if not rows:
            break

        # dict 변환 + None 처리 + PG에 없는 컬럼 제거
        records = [dict(row) for row in rows]

        for record in records:
            for col in timestamp_cols:
                if col in record and record[col] == "":
                    record[col] = None
            for col in boolean_cols:
                if col in record and isinstance(record[col], int):
                    record[col] = bool(record[col])

        # PG에 없는 컬럼 제거 (SQLite-only 컬럼 필터링)
        if pg_cols:
            records = [{k: v for k, v in r.items() if k in pg_cols} for r in records]

        if not records or not records[0]:
            offset += CHUNK_SIZE
            continue

        def _build_insert_sql(columns: Sequence[str]) -> str:
            sql = (
                f"INSERT INTO {table_name} ({', '.join(columns)}) "
                f"VALUES ({', '.join(':' + k for k in columns)})"
            )
            if allow_existing_rows:
                sql += " ON CONFLICT DO NOTHING"
            return sql

        def _try_insert(recs, label=""):
            """청크 삽입 시도, 실패 시 nullable FK null처리 → 행별 삽입 순으로 폴백"""
            try:
                with pg_engine.begin() as dst:
                    result = dst.execute(
                        text(_build_insert_sql(list(recs[0].keys()))),
                        recs,
                    )
                inserted = result.rowcount if result.rowcount is not None and result.rowcount >= 0 else len(recs)
                skipped = max(len(recs) - inserted, 0) if allow_existing_rows else 0
                if skipped:
                    print(f"  [충돌무시] {table_name} {label}: {inserted}행 이관, {skipped}행 중복 스킵")
                return inserted, skipped
            except Exception as e:
                err_str = str(e)
                # FK 위반 + nullable FK 컬럼이 있으면 NULL로 재시도
                if "ForeignKeyViolation" in err_str or "violates foreign key constraint" in err_str:
                    pg_fk_cols = _get_nullable_fk_cols(pg_engine, table_name)
                    if pg_fk_cols:
                        try:
                            nullified = [{k: (None if k in pg_fk_cols else v) for k, v in r.items()} for r in recs]
                            with pg_engine.begin() as dst2:
                                result = dst2.execute(
                                    text(_build_insert_sql(list(nullified[0].keys()))),
                                    nullified,
                                )
                            inserted = result.rowcount if result.rowcount is not None and result.rowcount >= 0 else len(nullified)
                            skipped = max(len(nullified) - inserted, 0) if allow_existing_rows else 0
                            print(f"  [FK null처리] {table_name} {label}: {len(pg_fk_cols)}개 컬럼 NULL 처리")
                            if skipped:
                                print(f"  [충돌무시] {table_name} {label}: {inserted}행 이관, {skipped}행 중복 스킵")
                            return inserted, skipped
                        except Exception:
                            pass  # fall through to row-by-row
                # 행별 삽입 폴백 (제약 위반 행만 스킵)
                row_ok = 0
                row_skip = 0
                for r in recs:
                    try:
                        with pg_engine.begin() as dst3:
                            result = dst3.execute(
                                text(_build_insert_sql(list(r.keys()))),
                                [r],
                            )
                        if result.rowcount is not None and result.rowcount == 0:
                            row_skip += 1
                        else:
                            row_ok += 1
                    except Exception as row_error:
                        row_skip += 1
                        if allow_existing_rows:
                            print(f"  [행별 충돌/실패] {table_name} {label}: {row_error}")
                if row_skip > 0:
                    print(f"  [행별] {table_name} {label}: {row_ok}행 이관, {row_skip}행 스킵")
                return row_ok, row_skip

        ok, skip = _try_insert(records, f"offset={offset}")
        migrated += ok
        failed += skip

        offset += CHUNK_SIZE

    return migrated, failed


def _get_nullable_fk_cols(pg_engine, table_name: str) -> list:
    """PG 테이블의 nullable FK 컬럼 목록 반환"""
    with pg_engine.connect() as conn:
        result = conn.execute(text("""
            SELECT kcu.column_name
            FROM information_schema.key_column_usage kcu
            JOIN information_schema.table_constraints tc
                ON kcu.constraint_name = tc.constraint_name
                AND kcu.table_schema = tc.table_schema
            JOIN information_schema.columns c
                ON c.table_schema = kcu.table_schema
                AND c.table_name = kcu.table_name
                AND c.column_name = kcu.column_name
            WHERE tc.constraint_type = 'FOREIGN KEY'
                AND kcu.table_schema = current_schema()
                AND kcu.table_name = :t
                AND c.is_nullable = 'YES'
        """), {"t": table_name})
        return [row[0] for row in result]


def sync_sequences(pg_engine) -> None:
    """SERIAL 컬럼 시퀀스를 MAX(id)로 동기화"""
    print("\n[3단계] SERIAL 시퀀스 동기화")
    pg_tables = get_pg_tables(pg_engine)
    synced = 0

    with pg_engine.begin() as conn:
        for table in SERIAL_TABLES:
            if table not in pg_tables:
                continue
            try:
                # 시퀀스 이름 확인
                seq_name = f"{table}_id_seq"
                result = conn.execute(text(
                    "SELECT EXISTS (SELECT 1 FROM pg_sequences WHERE schemaname = current_schema() AND sequencename = :seq)"
                ), {"seq": seq_name}).scalar()
                if not result:
                    continue

                conn.execute(text(
                    f"""
                    SELECT setval(
                        '{seq_name}',
                        COALESCE((SELECT MAX(id) FROM {table}), 1),
                        (SELECT MAX(id) IS NOT NULL FROM {table})
                    )
                    """
                ))
                synced += 1
            except Exception as e:
                print(f"  [경고] {table} 시퀀스 동기화 실패: {e}")

    print(f"  -> {synced}개 시퀀스 동기화 완료")


def verify_row_counts(sqlite_engine, pg_engine, tables: List[str]) -> bool:
    """테이블별 행 수 비교. 불일치 시 False 반환"""
    print("\n[4단계] 행 수 검증")
    all_ok = True
    issues = []

    for table in tables:
        with sqlite_engine.connect() as src:
            sqlite_count = src.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()

        pg_tables = get_pg_tables(pg_engine)
        if table not in pg_tables:
            print(f"  [경고] {table}: PG에 없음 (스키마 미생성)")
            continue

        with pg_engine.connect() as dst:
            pg_count = dst.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()

        status = "OK" if sqlite_count == pg_count else "MISMATCH"
        print(f"  {status:8s} {table}: SQLite={sqlite_count}, PG={pg_count}")
        if sqlite_count != pg_count:
            all_ok = False
            issues.append(f"{table}: {sqlite_count} vs {pg_count}")

    if issues:
        print(f"\n불일치 테이블 ({len(issues)}개):")
        for issue in issues:
            print(f"  - {issue}")

    return all_ok


def main():
    parser = argparse.ArgumentParser(description="SQLite -> PostgreSQL 데이터 마이그레이션")
    parser.add_argument("--dry-run", action="store_true", help="스키마 생성 + 행 수 집계만 (데이터 이관 없음)")
    parser.add_argument("--sqlite-path", type=str, default=None,
                        help=f"SQLite DB 파일 경로 (기본값: {_DEFAULT_SQLITE_PATH})")
    parser.add_argument(
        "--tables",
        type=str,
        default=None,
        help="쉼표로 구분한 대상 테이블 목록 (예: writing_sources,generated_writings)",
    )
    args = parser.parse_args()

    sqlite_path = (Path(args.sqlite_path) if args.sqlite_path else _DEFAULT_SQLITE_PATH).resolve()
    if not sqlite_path.exists():
        print(f"ERROR: SQLite DB 파일을 찾을 수 없습니다: {sqlite_path}")
        print(f"  --sqlite-path 옵션으로 경로를 지정하거나, {_DEFAULT_SQLITE_PATH} 위치에 파일을 확인하세요.")
        sys.exit(1)
    sqlite_url = f"sqlite:///{sqlite_path.as_posix()}"
    selected_tables = parse_selected_tables_arg(args.tables)

    pg_url = get_pg_url()
    print(build_startup_banner(sqlite_path, sqlite_url, pg_url, selected_tables, args.dry_run))

    # 엔진 생성
    sqlite_engine = create_engine(sqlite_url)
    pg_engine = create_engine(pg_url, pool_pre_ping=True)

    # 1단계: PG 스키마 생성
    create_pg_schema(pg_engine)

    # 이관 대상 테이블 목록 + 누락 테이블 Reflection 생성
    try:
        tables = get_sqlite_tables(sqlite_engine, selected_tables=selected_tables)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        sqlite_engine.dispose()
        pg_engine.dispose()
        sys.exit(1)
    pg_tables = get_pg_tables(pg_engine)
    missing_in_pg = [t for t in tables if t not in pg_tables]
    if missing_in_pg:
        print(f"\n  [추가] ORM/init_extra_tables에 없는 {len(missing_in_pg)}개 테이블 → SQLite reflection 생성")
        create_missing_tables_from_sqlite(sqlite_engine, pg_engine, missing_in_pg)
        pg_tables = get_pg_tables(pg_engine)  # 재조회
    print(f"\n이관 대상: {len(tables)}개 테이블 (선택: {format_selected_tables(selected_tables)} | 제외 {len(EXCLUDED_TABLES)}개)")

    # 2단계: 데이터 이관 (FK 의존성 순서 처리를 위한 다중 패스)
    if not args.dry_run:
        print(f"\n[2단계] 데이터 이관 (청크: {CHUNK_SIZE}행, FK 의존성 다중 패스)")
        total_migrated = 0
        total_failed = 0
        skipped_tables = []

        pending_tables = [t for t in tables if t in pg_tables]
        for table in tables:
            if table not in pg_tables:
                print(f"  [스킵] {table}: PG에 테이블 없음")
                skipped_tables.append(table)

        MAX_PASSES = 5
        for pass_num in range(1, MAX_PASSES + 1):
            if not pending_tables:
                break
            print(f"\n  --- 패스 {pass_num} ({len(pending_tables)}개 테이블) ---")
            retry_tables = []
            for table in pending_tables:
                allow_existing_rows = bool(selected_tables and table in selected_tables)
                migrated, failed = migrate_table(
                    sqlite_engine,
                    pg_engine,
                    table,
                    dry_run=False,
                    allow_existing_rows=allow_existing_rows,
                )
                total_migrated += migrated
                if migrated > 0:
                    print(f"  [완료] {table}: {migrated}행 이관")
                elif failed == 0 and migrated == 0:
                    pass  # 이미 건너뜀(건너뜀 메시지 출력됨) 또는 0행
                if failed > 0:
                    total_failed += failed
                    retry_tables.append(table)
            pending_tables = retry_tables

        if pending_tables:
            print(f"\n  최종 실패 테이블 ({len(pending_tables)}개): {', '.join(pending_tables)}")
        print(f"\n이관 완료: 총 {total_migrated}행, 실패 {total_failed}행")
        if skipped_tables:
            print(f"스킵된 테이블 ({len(skipped_tables)}개): {', '.join(skipped_tables)}")

        # 3단계: 시퀀스 동기화
        sync_sequences(pg_engine)
    else:
        print("\n[2단계] DRY RUN - 이관 건너뜀 (행 수 집계 생략)")
        missing_tables = [t for t in tables if t not in pg_tables]
        ok_tables = [t for t in tables if t in pg_tables]
        print(f"  PG 스키마 OK: {len(ok_tables)}개 테이블")
        if missing_tables:
            print(f"  PG 스키마 없음: {len(missing_tables)}개 테이블")
            for t in missing_tables:
                print(f"    - {t}")

    # 4단계: 행 수 검증 (실제 이관 후에만 실행)
    if not args.dry_run:
        migratable_tables = [t for t in tables if t in pg_tables]
        all_ok = verify_row_counts(sqlite_engine, pg_engine, migratable_tables)
    else:
        all_ok = True
        print("\n[4단계] DRY RUN - 행 수 검증 생략")

    # 정리
    sqlite_engine.dispose()
    pg_engine.dispose()

    print("\n" + "=" * 60)
    if args.dry_run:
        print("DRY RUN 완료 - 실제 이관 없음. 스키마 확인 완료.")
        sys.exit(0)
    elif all_ok:
        print("마이그레이션 완료 - 모든 테이블 행 수 일치")
        sys.exit(0)
    else:
        print("마이그레이션 완료 - 일부 테이블 불일치 (위 로그 확인)")
        sys.exit(1)


if __name__ == "__main__":
    main()
