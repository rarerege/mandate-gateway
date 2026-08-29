from __future__ import annotations

import pytest

from app.db import get_conn, init_db


@pytest.fixture(autouse=True)
def clean_db():
    """Every test starts against a clean set of tables. Cheap enough at this
    scale (SQLite, hundreds of rows) that a shared fixture beats a
    per-test temp file for readability."""
    init_db()
    with get_conn() as conn:
        conn.executescript(
            "DELETE FROM agent_history; DELETE FROM seen_nonces; "
            "DELETE FROM order_events; DELETE FROM audit_log; DELETE FROM outcomes;"
        )
    yield
