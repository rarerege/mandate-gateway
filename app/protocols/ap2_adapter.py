"""Adapter for Google's Agent Payments Protocol (AP2)-style mandates.

Modeled on AP2's public spec: an Intent Mandate + Cart Mandate pair signed
as a Verifiable Credential. We only need the shape, not a full VC/JSON-LD
implementation, to demonstrate real protocol normalization.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.protocols.base import ProtocolAdapter
from app.schemas import NormalizedMandate, SourceProtocol


class AP2Adapter(ProtocolAdapter):
    name = "ap2"

    def to_normalized_mandate(self, raw_payload: dict[str, Any]) -> NormalizedMandate:
        agent = raw_payload["agent"]
        cart = raw_payload["cart"]
        timestamps = raw_payload["timestamps"]
        proof = raw_payload["proof"]

        return NormalizedMandate(
            mandate_id=raw_payload["mandate_id"],
            source_protocol=SourceProtocol.AP2,
            agent_id=agent["id"],
            agent_platform=agent["platform"],
            user_reference=raw_payload["user_reference"],
            merchant_id=raw_payload["merchant_id"],
            category=cart["category"],
            amount_minor_units=cart["amount_minor_units"],
            currency=cart.get("currency", "INR"),
            items_summary=cart["items_summary"],
            issued_at=datetime.fromisoformat(timestamps["issued_at"]),
            expires_at=datetime.fromisoformat(timestamps["expires_at"]),
            nonce=raw_payload["nonce"],
            signature=proof["signature"],
            signing_key_id=proof["signing_key_id"],
            raw_payload=raw_payload,
        )
