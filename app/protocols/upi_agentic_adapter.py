"""Adapter for NPCI/UPI-style agentic payment requests.

Modeled loosely on the shape of Razorpay+NPCI's agentic UPI announcement:
a VPA-addressed, agent-initiated collect request. Field names reflect UPI
conventions (VPA, paise amounts) rather than AP2/ACP's terms, which is
exactly the kind of format divergence Mandate Gateway exists to absorb.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.protocols.base import ProtocolAdapter
from app.schemas import NormalizedMandate, SourceProtocol


class UPIAgenticAdapter(ProtocolAdapter):
    name = "upi_agentic"

    def to_normalized_mandate(self, raw_payload: dict[str, Any]) -> NormalizedMandate:
        agent = raw_payload["agent_handle"]
        auth = raw_payload["auth_block"]

        return NormalizedMandate(
            mandate_id=raw_payload["txn_ref"],
            source_protocol=SourceProtocol.UPI_AGENTIC,
            agent_id=agent["handle_id"],
            agent_platform=agent["platform"],
            user_reference=raw_payload["payer_vpa_hash"],
            merchant_id=raw_payload["merchant_vpa"],
            category=raw_payload["merchant_category"],
            amount_minor_units=raw_payload["amount_paise"],
            currency="INR",
            items_summary=raw_payload["purpose_note"],
            issued_at=datetime.fromisoformat(raw_payload["initiated_at"]),
            expires_at=datetime.fromisoformat(raw_payload["valid_till"]),
            nonce=raw_payload["upi_ref_id"],
            signature=auth["signature"],
            signing_key_id=auth["signing_key_id"],
            raw_payload=raw_payload,
        )
