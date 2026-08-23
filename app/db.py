"""Tiny SQLite helper shared by the reputation store and audit log.

Deliberately not an ORM: this is a hackathon-scoped service and a thin
wrapper keeps the schema visible and the whole data layer auditable in one
file per concern.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "mandate_gateway.db"


@contextmanager
def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS agent_history (
                agent_id TEXT PRIMARY KEY,
                agent_platform TEXT NOT NULL,
                account_age_days INTEGER NOT NULL DEFAULT 0,
                prior_transaction_count INTEGER NOT NULL DEFAULT 0,
                prior_dispute_count INTEGER NOT NULL DEFAULT 0,
                prior_confirmed_fraud_count INTEGER NOT NULL DEFAULT 0,
                orders_last_hour INTEGER NOT NULL DEFAULT 0,
                last_seen_at TEXT
            );

            CREATE TABLE IF NOT EXISTS seen_nonces (
                nonce TEXT PRIMARY KEY,
                mandate_id TEXT NOT NULL,
                seen_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS order_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                agent_platform TEXT NOT NULL DEFAULT '',
                merchant_id TEXT NOT NULL DEFAULT '',
                occurred_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_order_events_agent ON order_events(agent_id, occurred_at);
            CREATE INDEX IF NOT EXISTS idx_order_events_platform_merchant
                ON order_events(agent_platform, merchant_id, occurred_at);

            CREATE TABLE IF NOT EXISTS audit_log (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                decision_id TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                prev_hash TEXT NOT NULL,
                entry_hash TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS outcomes (
                decision_id TEXT PRIMARY KEY,
                was_legitimate INTEGER NOT NULL,
                note TEXT,
                recorded_at TEXT NOT NULL
            );
            """
        )


if __name__ == "__main__":
    init_db()
    print(f"Initialized database at {DB_PATH}")
