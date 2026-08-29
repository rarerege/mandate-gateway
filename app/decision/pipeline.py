"""The orchestrator: wires every component into one authorization call.

    inbound mandate (any protocol)
        -> normalize                (app/protocols)
        -> verify                   (app/verification)   -- security boundary
        -> score reputation         (app/reputation)      -- ML
        -> evaluate policy          (app/policy)          -- deterministic rules
        -> decide + explain         (app/reasoning)       -- LLM narrates, never decides
        -> escalate if STEP_UP      (app/escalation)
        -> log immutably            (app/audit)
        -> update agent history     (app/reputation.store)

This is the single place that matters most in a code review: every other
module is independently unit-testable, but this file is where an outsider
can see the actual guardrail — the decision boundary in reasoner.decide_action
runs before any LLM call, and nothing here can approve an order whose
verification failed.
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone

from app.audit.log import append_entry
from app.escalation.handler import StepUpRequest, StepUpResponse, send_step_up_request
from app.policy.engine import PolicyEngine
from app.protocols.registry import get_adapter
from app.reasoning.reasoner import decide_action, generate_rationale
from app.reputation.model import ReputationModel
from app.reputation.store import get_or_create_agent, record_order_event, record_outcome
from app.schemas import Decision, GatewayDecision, SourceProtocol
from app.verification.trust_roots import REGISTRY
from app.verification.verifier import verify_mandate


class MandateGatewayPipeline:
    def __init__(self, policy_engine: PolicyEngine | None = None, reputation_model: ReputationModel | None = None):
        self.policy_engine = policy_engine or PolicyEngine()
        self.reputation_model = reputation_model or ReputationModel.load()

    def authorize(
        self,
        raw_payload: dict,
        protocol: SourceProtocol,
        auto_step_up_response: StepUpResponse | None = None,
        verbose_escalation: bool = True,
    ) -> GatewayDecision:
        start = time.perf_counter()

        adapter = get_adapter(protocol)
        mandate = adapter.to_normalized_mandate(raw_payload)

        verification = verify_mandate(mandate, REGISTRY)

        snapshot = get_or_create_agent(mandate.agent_id, mandate.agent_platform)
        reputation = self.reputation_model.score(mandate, snapshot)

        policy = self.policy_engine.evaluate(mandate, snapshot.orders_last_hour)

        decision, confidence = decide_action(verification, reputation, policy)
        pre_escalation_decision = decision

        # Rationale is generated against the *pre-escalation* decision: the
        # explanation for "why did the gateway want a human here" must not
        # retroactively read as "reputation adequate" just because a human
        # then approved it. The escalation outcome is appended afterwards
        # as its own, clearly separate sentence.
        rationale = generate_rationale(mandate, verification, reputation, policy, pre_escalation_decision)

        if decision == Decision.STEP_UP:
            reason = "; ".join(policy.rule_hits) if policy.rule_hits else f"reputation score {reputation.score:.2f} below threshold"
            response = send_step_up_request(
                StepUpRequest(
                    merchant_id=mandate.merchant_id,
                    agent_id=mandate.agent_id,
                    amount_minor_units=mandate.amount_minor_units,
                    category=mandate.category,
                    reason=reason,
                ),
                auto_response=auto_step_up_response,
                verbose=verbose_escalation,
            )
            rationale += (
                f" Escalated to merchant '{mandate.merchant_id}' for step-up review — "
                f"response: {'APPROVED' if response.approved else 'NOT APPROVED'} "
                f"(by {response.responder}{': ' + response.note if response.note else ''})."
            )
            if response.approved:
                decision = Decision.APPROVE
                confidence = min(0.95, confidence + 0.1)
            else:
                # STEP_UP is never a final decision — it always resolves to
                # either APPROVE (human approved) or REJECT (human declined,
                # or nobody was there to ask). Defaulting an unanswered
                # step-up to reject is deliberate: see handler.py.
                decision = Decision.REJECT
                confidence = min(0.95, confidence + 0.1)

        # Only record the order event (which feeds future velocity checks)
        # once we know the request was genuinely processed, not replayed.
        if verification.not_replayed:
            record_order_event(mandate.agent_id)

        latency_ms = (time.perf_counter() - start) * 1000

        result = GatewayDecision(
            decision_id=str(uuid.uuid4()),
            mandate_id=mandate.mandate_id,
            agent_id=mandate.agent_id,
            merchant_id=mandate.merchant_id,
            decision=decision,
            pre_escalation_decision=pre_escalation_decision,
            confidence=confidence,
            rationale=rationale,
            verification=verification,
            reputation=reputation,
            policy=policy,
            latency_ms=latency_ms,
            created_at=datetime.now(timezone.utc),
        )

        entry_hash = append_entry(result.decision_id, result.model_dump(mode="json"))
        result.audit_hash = entry_hash
        return result

    def record_outcome(self, agent_id: str, was_legitimate: bool) -> None:
        record_outcome(agent_id, was_legitimate)
