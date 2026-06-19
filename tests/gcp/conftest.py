"""
Shared fixtures for tests/gcp/.

Stubs app.core.database before any test imports can cascade into it.
The real database module does not exist in the worktree (it lives in
app/core/database.py which requires a running PostgreSQL connection at
import time).  All BigQuery export tests are pure unit tests that do not
need a real DB connection — they mock the SQLAlchemy session.
"""

import sys
from unittest.mock import MagicMock
from sqlalchemy.orm import declarative_base

# Install stub as early as possible (module-level, runs at conftest collection time)
if "app.core.database" not in sys.modules:
    _real_base = declarative_base()
    _db_stub = MagicMock()
    _db_stub.Base = _real_base
    _db_stub.SessionLocal = MagicMock()
    _db_stub.get_db = MagicMock()
    _db_stub.engine = MagicMock()
    _db_stub.init_extra_tables = MagicMock()
    _db_stub.db_circuit = MagicMock()
    _db_stub._CLOSED = False
    sys.modules["app.core.database"] = _db_stub
    # Also stub app.database (older alias)
    sys.modules.setdefault("app.database", _db_stub)
