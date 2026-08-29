"""Builds realistic, *actually signed* raw protocol payloads for demos and
evaluation — the same canonical-byte-string signing logic the real
verifier checks against, so a passing test here means something.
"""
from __future__ import annotations

import base64
import uuid
from datetime import datetime, timedelta, timezone

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.schemas import NormalizedMandate, SourceProtocol
from app.verification.signer import sign


def _sign_canonical(
    mandate_id: str,
    protocol: SourceProtocol,
    agent_id: str,
    agent_platform: str,
    merchant_id: str,
    category: str,
    amount_minor_units: int,
    currency: str,
    issued_at: datetime,
    expires_at: datetime,
    nonce: str,
    private_key: Ed25519PrivateKey,
) -> str:
    # agent_platform is part of the signed canonical bytes (see
    # NormalizedMandate.canonical_signing_bytes) precisely so a mandate
    # can't be relabelled to a different platform after signing — so it
    # must be the *real* value here, not a placeholder distinct from what
    # actually ships in the payload.
    placeholder = NormalizedMandate(
        mandate_id=mandate_id,
        source_protocol=protocol,
        agent_id=agent_id,
        agent_platform=agent_platform,
        user_reference="placeholder",
        merchant_id=merchant_id,
        category=category,
        amount_minor_units=amount_minor_units,
        currency=currency,
        items_summary="placeholder",
        issued_at=issued_at,
        expires_at=expires_at,
        nonce=nonce,
        signature="",
        signing_key_id="placeholder",
    )
    return sign(private_key, placeholder.canonical_signing_bytes())


def build_ap2_payload(
    *,
    agent_id: str,
    agent_platform: str,
    merchant_id: str,
    category: str,
    amount_minor_units: int,
    key_id: str,
    private_key: Ed25519PrivateKey,
    currency: str = "INR",
    issued_at: datetime | None = None,
    ttl_minutes: int = 15,
    nonce: str | None = None,
    tamper_signature: bool = False,
) -> dict:
    mandate_id = f"ap2-{uuid.uuid4()}"
    issued_at = issued_at or datetime.now(timezone.utc)
    expires_at = issued_at + timedelta(minutes=ttl_minutes)
    nonce = nonce or str(uuid.uuid4())

    signature = _sign_canonical(
        mandate_id, SourceProtocol.AP2, agent_id, agent_platform, merchant_id, category,
        amount_minor_units, currency, issued_at, expires_at, nonce, private_key,
    )
    if tamper_signature:
        signature = _flip_signature(signature)

    return {
        "mandate_id": mandate_id,
        "protocol": "AP2",
        "agent": {"id": agent_id, "platform": agent_platform},
        "user_reference": f"user-hash-{uuid.uuid4().hex[:12]}",
        "merchant_id": merchant_id,
        "cart": {
            "category": category,
            "amount_minor_units": amount_minor_units,
            "currency": currency,
            "items_summary": f"1x item in category '{category}'",
        },
        "timestamps": {"issued_at": issued_at.isoformat(), "expires_at": expires_at.isoformat()},
        "nonce": nonce,
        "proof": {"signature": signature, "signing_key_id": key_id},
    }


def build_acp_payload(
    *,
    agent_id: str,
    agent_platform: str,
    merchant_id: str,
    category: str,
    amount_minor_units: int,
    key_id: str,
    private_key: Ed25519PrivateKey,
    currency: str = "INR",
    issued_at: datetime | None = None,
    ttl_minutes: int = 15,
    nonce: str | None = None,
    tamper_signature: bool = False,
) -> dict:
    mandate_id = f"acp-{uuid.uuid4()}"
    issued_at = issued_at or datetime.now(timezone.utc)
    expires_at = issued_at + timedelta(minutes=ttl_minutes)
    nonce = nonce or str(uuid.uuid4())

    signature = _sign_canonical(
        mandate_id, SourceProtocol.ACP, agent_id, agent_platform, merchant_id, category,
        amount_minor_units, currency, issued_at, expires_at, nonce, private_key,
    )
    if tamper_signature:
        signature = _flip_signature(signature)

    return {
        "id": mandate_id,
        "buyer_agent": {"agent_id": agent_id, "platform": agent_platform},
        "buyer_reference": f"user-hash-{uuid.uuid4().hex[:12]}",
        "checkout_session": {
            "merchant_id": merchant_id,
            "category": category,
            "total_amount_minor_units": amount_minor_units,
            "currency": currency,
            "line_items_summary": f"1x item in category '{category}'",
            "created_at": issued_at.isoformat(),
            "expires_at": expires_at.isoformat(),
        },
        "authorization": {"idempotency_key": nonce, "signature": signature, "signing_key_id": key_id},
    }


def build_upi_agentic_payload(
    *,
    agent_id: str,
    agent_platform: str,
    merchant_id: str,
    category: str,
    amount_minor_units: int,
    key_id: str,
    private_key: Ed25519PrivateKey,
    currency: str = "INR",
    issued_at: datetime | None = None,
    ttl_minutes: int = 15,
    nonce: str | None = None,
    tamper_signature: bool = False,
) -> dict:
    mandate_id = f"upi-{uuid.uuid4()}"
    issued_at = issued_at or datetime.now(timezone.utc)
    expires_at = issued_at + timedelta(minutes=ttl_minutes)
    nonce = nonce or str(uuid.uuid4())

    signature = _sign_canonical(
        mandate_id, SourceProtocol.UPI_AGENTIC, agent_id, agent_platform, merchant_id, category,
        amount_minor_units, currency, issued_at, expires_at, nonce, private_key,
    )
    if tamper_signature:
        signature = _flip_signature(signature)

    return {
        "txn_ref": mandate_id,
        "agent_handle": {"handle_id": agent_id, "platform": agent_platform},
        "payer_vpa_hash": f"vpa-hash-{uuid.uuid4().hex[:12]}",
        "merchant_vpa": merchant_id,
        "merchant_category": category,
        "amount_paise": amount_minor_units,
        "purpose_note": f"1x item in category '{category}'",
        "initiated_at": issued_at.isoformat(),
        "valid_till": expires_at.isoformat(),
        "upi_ref_id": nonce,
        "auth_block": {"signature": signature, "signing_key_id": key_id},
    }


def _flip_signature(signature_b64: str) -> str:
    raw = bytearray(base64.b64decode(signature_b64))
    raw[0] ^= 0xFF
    return base64.b64encode(bytes(raw)).decode("ascii")


BUILDERS = {
    SourceProtocol.AP2: build_ap2_payload,
    SourceProtocol.ACP: build_acp_payload,
    SourceProtocol.UPI_AGENTIC: build_upi_agentic_payload,
}
