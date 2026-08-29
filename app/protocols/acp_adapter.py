"""Adapter for Stripe/OpenAI's Agentic Commerce Protocol (ACP)-style orders.

ACP's real wire format centers on a checkout session object with a buying
agent attached. Field names below mirror that shape closely enough to
prove the normalization is doing real structural translation, not just
renaming one dict into another.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.protocols.base import ProtocolAdapter
from app.schemas import NormalizedMandate, SourceProtocol


class ACPAdapter(ProtocolAdapter):
    name = "acp"

    def to_normalized_mandate(self, raw_payload: dict[str, Any]) -> NormalizedMandate:
        session = raw_payload["checkout_session"]
        buyer_agent = raw_payload["buyer_agent"]
        auth = raw_payload["authorization"]

        return NormalizedMandate(
            mandate_id=raw_payload["id"],
            source_protocol=SourceProtocol.ACP,
            agent_id=buyer_agent["agent_id"],
            agent_platform=buyer_agent["platform"],
            user_reference=raw_payload["buyer_reference"],
            merchant_id=session["merchant_id"],
            category=session["category"],
            amount_minor_units=session["total_amount_minor_units"],
            currency=session.get("currency", "INR"),
            items_summary=session["line_items_summary"],
            issued_at=datetime.fromisoformat(session["created_at"]),
            expires_at=datetime.fromisoformat(session["expires_at"]),
            nonce=auth["idempotency_key"],
            signature=auth["signature"],
            signing_key_id=auth["signing_key_id"],
            raw_payload=raw_payload,
        )
