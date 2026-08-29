"""Mandate verification: the security-critical core of the gateway.

Four independent checks, all of which must pass:
  1. Signature  — was this exact payload signed by a key we recognise?
  2. Expiry     — is `expires_at` still in the future?
  3. Replay     — has this nonce been seen before (same mandate re-sent)?
  4. Trust root — is the signing key registered at all?

Each check is intentionally cheap, deterministic, and independent of any
LLM call — an authorization boundary is not something to hand to a language
model's judgment; the LLM's job (see app/reasoning/) is to *explain* the
outcome of these checks, never to override them.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone

from cryptography.exceptions import InvalidSignature

from app.db import get_conn
from app.schemas import NormalizedMandate, VerificationResult
from app.verification.trust_roots import TrustRootRegistry


def _is_replay(nonce: str, mandate_id: str) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM seen_nonces WHERE nonce = ?", (nonce,)
        ).fetchone()
        if row is not None:
            return True
        conn.execute(
            "INSERT INTO seen_nonces (nonce, mandate_id, seen_at) VALUES (?, ?, ?)",
            (nonce, mandate_id, datetime.now(timezone.utc).isoformat()),
        )
        return False


def verify_mandate(
    mandate: NormalizedMandate, registry: TrustRootRegistry
) -> VerificationResult:
    reasons: list[str] = []

    trust_root = registry.get(mandate.signing_key_id)
    trust_root_known = trust_root is not None
    if not trust_root_known:
        reasons.append(f"signing key '{mandate.signing_key_id}' is not a registered trust root")

    signature_valid = False
    if trust_root_known:
        try:
            signature_bytes = base64.b64decode(mandate.signature)
            trust_root.public_key.verify(signature_bytes, mandate.canonical_signing_bytes())
            signature_valid = True
        except (InvalidSignature, ValueError, base64.binascii.Error):
            reasons.append("signature does not match canonical payload (tampered or wrong key)")
    else:
        reasons.append("signature not checked: no trust root to verify against")

    not_expired = mandate.expires_at.astimezone(timezone.utc) > datetime.now(timezone.utc)
    if not not_expired:
        reasons.append(f"mandate expired at {mandate.expires_at.isoformat()}")

    not_replayed = not _is_replay(mandate.nonce, mandate.mandate_id)
    if not not_replayed:
        reasons.append(f"nonce '{mandate.nonce}' was already used by a prior request (replay)")

    if not reasons:
        reasons.append("all checks passed")

    return VerificationResult(
        signature_valid=signature_valid,
        not_expired=not_expired,
        not_replayed=not_replayed,
        trust_root_known=trust_root_known,
        reasons=reasons,
    )
