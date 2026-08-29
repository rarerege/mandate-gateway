"""Hash-chained audit log.

Every decision is appended with a hash of (payload + previous entry's
hash). Nobody can quietly edit or delete a past decision without breaking
every hash after it — the same tamper-evidence idea a blockchain uses,
applied to a single authoritative log rather than a distributed ledger,
which is the right amount of machinery for what this actually needs to
prove: "this audit trail has not been retroactively edited."
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from app.db import get_conn

GENESIS_HASH = "0" * 64


def _hash_entry(prev_hash: str, payload_json: str) -> str:
    return hashlib.sha256((prev_hash + payload_json).encode("utf-8")).hexdigest()


def append_entry(decision_id: str, payload: dict) -> str:
    payload_json = json.dumps(payload, sort_keys=True, default=str)
    with get_conn() as conn:
        row = conn.execute(
            "SELECT entry_hash FROM audit_log ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        prev_hash = row["entry_hash"] if row else GENESIS_HASH
        entry_hash = _hash_entry(prev_hash, payload_json)
        conn.execute(
            """INSERT INTO audit_log (decision_id, created_at, payload_json, prev_hash, entry_hash)
               VALUES (?, ?, ?, ?, ?)""",
            (decision_id, datetime.now(timezone.utc).isoformat(), payload_json, prev_hash, entry_hash),
        )
        return entry_hash


def get_entry(decision_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM audit_log WHERE decision_id = ?", (decision_id,)
        ).fetchone()
        if row is None:
            return None
        return {
            "decision_id": row["decision_id"],
            "created_at": row["created_at"],
            "payload": json.loads(row["payload_json"]),
            "prev_hash": row["prev_hash"],
            "entry_hash": row["entry_hash"],
        }


def verify_chain_integrity() -> tuple[bool, str]:
    """Recomputes every hash in sequence; returns (ok, message). Exposed as
    a script/test so 'tamper-evident' is a claim you can actually check,
    not just assert in a README."""
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM audit_log ORDER BY seq ASC").fetchall()

    expected_prev = GENESIS_HASH
    for row in rows:
        if row["prev_hash"] != expected_prev:
            return False, f"chain broken before decision {row['decision_id']} (seq {row['seq']})"
        recomputed = _hash_entry(row["prev_hash"], row["payload_json"])
        if recomputed != row["entry_hash"]:
            return False, f"entry hash mismatch at decision {row['decision_id']} (seq {row['seq']}) — payload was likely edited"
        expected_prev = row["entry_hash"]

    return True, f"chain intact across {len(rows)} entries"
