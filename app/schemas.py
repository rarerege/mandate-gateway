"""
Core data contracts for Mandate Gateway.

These are the canonical, protocol-agnostic shapes that every inbound
agent-commerce protocol (AP2, ACP, UPI-agentic, ...) gets normalized into,
and the shapes the decision pipeline produces on the way out.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class SourceProtocol(str, Enum):
    AP2 = "ap2"
    ACP = "acp"
    UPI_AGENTIC = "upi_agentic"


class Decision(str, Enum):
    APPROVE = "approve"
    STEP_UP = "step_up"
    REJECT = "reject"


class NormalizedMandate(BaseModel):
    """Protocol-agnostic view of an inbound agent-initiated order.

    Every protocol adapter (see app/protocols/) is responsible for producing
    one of these from whatever wire format it receives. Nothing downstream of
    this model needs to know which protocol the order arrived on.
    """

    mandate_id: str
    source_protocol: SourceProtocol
    agent_id: str = Field(..., description="Stable identifier for the issuing agent/platform")
    agent_platform: str = Field(..., description="e.g. 'openai-chatgpt', 'google-gemini', 'npci-upi'")
    user_reference: str = Field(..., description="Pseudonymous reference to the end human, never PII")
    merchant_id: str
    category: str
    amount_minor_units: int = Field(..., description="Order amount in minor currency units (paise/cents)")
    currency: str = "INR"
    items_summary: str
    issued_at: datetime
    expires_at: datetime
    nonce: str = Field(..., description="Single-use value; prevents mandate replay")
    signature: str = Field(..., description="Base64-encoded Ed25519 signature over the canonical payload")
    signing_key_id: str = Field(..., description="Which registered trust-root key signed this mandate")
    raw_payload: dict = Field(default_factory=dict, description="Original protocol-native payload, for audit")

    def canonical_signing_bytes(self) -> bytes:
        """The exact byte string the signature is computed over.

        Field order and formatting are fixed on purpose: verification must
        recompute *exactly* this string or every legitimate mandate fails.
        """
        parts = [
            self.mandate_id,
            self.source_protocol.value,
            self.agent_id,
            self.merchant_id,
            self.category,
            str(self.amount_minor_units),
            self.currency,
            self.issued_at.astimezone(timezone.utc).isoformat(),
            self.expires_at.astimezone(timezone.utc).isoformat(),
            self.nonce,
        ]
        return "|".join(parts).encode("utf-8")


class VerificationResult(BaseModel):
    signature_valid: bool
    not_expired: bool
    not_replayed: bool
    trust_root_known: bool
    reasons: list[str] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.signature_valid and self.not_expired and self.not_replayed and self.trust_root_known


class ReputationResult(BaseModel):
    agent_id: str
    score: float = Field(..., ge=0.0, le=1.0, description="Higher = more trustworthy")
    features: dict = Field(default_factory=dict)
    prior_transaction_count: int = 0
    prior_dispute_rate: float = 0.0


class PolicyEvaluation(BaseModel):
    allowed_category: bool
    within_amount_cap: bool
    within_velocity_cap: bool
    requires_step_up_by_policy: bool
    rule_hits: list[str] = Field(default_factory=list)

    @property
    def hard_block(self) -> bool:
        """A clear, non-negotiable policy violation (category or amount).

        Velocity and step-up triggers are handled separately in the decision
        reasoner because they warrant escalation, not an automatic reject —
        a legitimate agent can still have a burst of orders.
        """
        return not (self.allowed_category and self.within_amount_cap)


class GatewayDecision(BaseModel):
    decision_id: str
    mandate_id: str
    agent_id: str
    merchant_id: str
    decision: Decision
    pre_escalation_decision: Decision
    confidence: float = Field(..., ge=0.0, le=1.0)
    rationale: str
    verification: VerificationResult
    reputation: ReputationResult
    policy: PolicyEvaluation
    latency_ms: float
    created_at: datetime
    audit_hash: Optional[str] = None


class OutcomeReport(BaseModel):
    """Ground truth fed back after the fact, e.g. from a chargeback or a
    confirmed-good delivery. Closes the learning loop for the reputation
    model."""

    decision_id: str
    was_legitimate: bool
    note: str = ""
