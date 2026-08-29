"""Idempotent demo setup: trust-root keys + a small seeded agent population.

Run directly (`python -m scripts.seed_demo`) or imported — `ensure_seeded()`
is safe to call multiple times and is what app/main.py calls on startup so
the API and the CLI scripts always agree on the same keys and agents.
"""
from __future__ import annotations

import json
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.db import init_db
from app.reputation.store import seed_agent_stats
from app.verification.signer import generate_keypair, public_key_to_hex
from app.verification.trust_roots import REGISTRY, TrustRoot

KEYS_PATH = Path(__file__).resolve().parent.parent / "data" / "demo_keys.json"

# key_id -> platform that key belongs to
TRUST_ROOT_KEYS = {
    "ap2-google-2026-01": "google-gemini",
    "acp-openai-2026-01": "openai-chatgpt",
    "upi-npci-claude-2026-01": "npci-upi-agentic",
    # deliberately NOT registered — used to demonstrate an unknown-issuer rejection
    # "acp-shadow-issuer-2026-01": "unknown-shadow-platform",
}

# agent_id -> (platform, account_age_days, prior_tx, prior_disputes, prior_fraud)
DEMO_AGENTS = {
    "agent-longtrust-nova": ("google-gemini", 540, 210, 2, 0),
    "agent-newcomer-atlas": ("openai-chatgpt", 1, 0, 0, 0),
    "agent-ringleader-vex": ("openai-chatgpt", 40, 30, 9, 6),
    "agent-npci-shopper-01": ("npci-upi-agentic", 200, 80, 1, 0),
}

_PRIVATE_KEYS: dict[str, Ed25519PrivateKey] = {}
_seeded = False


def _load_or_create_keys() -> dict[str, Ed25519PrivateKey]:
    KEYS_PATH.parent.mkdir(parents=True, exist_ok=True)
    if KEYS_PATH.exists():
        stored = json.loads(KEYS_PATH.read_text())
        return {
            key_id: Ed25519PrivateKey.from_private_bytes(bytes.fromhex(entry["private_key_hex"]))
            for key_id, entry in stored.items()
        }

    keys: dict[str, Ed25519PrivateKey] = {}
    stored = {}
    for key_id, platform in TRUST_ROOT_KEYS.items():
        private_key, _public_key = generate_keypair()
        keys[key_id] = private_key
        raw_hex = private_key.private_bytes_raw().hex()
        stored[key_id] = {"platform": platform, "private_key_hex": raw_hex}
    KEYS_PATH.write_text(json.dumps(stored, indent=2))
    return keys


def ensure_seeded() -> None:
    global _seeded, _PRIVATE_KEYS
    init_db()

    _PRIVATE_KEYS = _load_or_create_keys()
    for key_id, private_key in _PRIVATE_KEYS.items():
        platform = TRUST_ROOT_KEYS[key_id]
        REGISTRY.register(TrustRoot(key_id=key_id, platform=platform, public_key=private_key.public_key()))

    for agent_id, (platform, age, tx, disputes, fraud) in DEMO_AGENTS.items():
        seed_agent_stats(
            agent_id=agent_id,
            agent_platform=platform,
            account_age_days=age,
            prior_transaction_count=tx,
            prior_dispute_count=disputes,
            prior_confirmed_fraud_count=fraud,
        )

    _seeded = True


def get_demo_private_key(key_id: str) -> Ed25519PrivateKey:
    if not _PRIVATE_KEYS:
        ensure_seeded()
    return _PRIVATE_KEYS[key_id]


if __name__ == "__main__":
    ensure_seeded()
    print(f"Seeded {len(TRUST_ROOT_KEYS)} trust-root keys and {len(DEMO_AGENTS)} demo agents.")
    print(f"Keys persisted at {KEYS_PATH} (reused on every future run).")
