"""Decision reasoning: turns three independent signals into one decision.

Design choice worth calling out explicitly: the *decision boundary* below
is plain Python, not an LLM call. An LLM is a poor place to put an
authorization boundary — it is exactly the kind of component a prompt
injection (e.g. hidden text inside `items_summary`) could try to talk its
way around. So the LLM (or the template fallback when no API key is
configured) only ever narrates a decision that has already been made
deterministically; it cannot change the outcome, only explain it.
"""
from __future__ import annotations

import os

from app.schemas import (
    Decision,
    GatewayDecision,
    NormalizedMandate,
    PolicyEvaluation,
    ReputationResult,
    VerificationResult,
)

REPUTATION_STEP_UP_BELOW = 0.55
REPUTATION_REJECT_BELOW = 0.20


def decide_action(
    verification: VerificationResult,
    reputation: ReputationResult,
    policy: PolicyEvaluation,
) -> tuple[Decision, float]:
    """Pure function: signals in, (decision, confidence) out. Unit-testable
    without touching a database, a model file, or an LLM.

    One deliberate design choice worth flagging: a low reputation score
    alone is *not* sufficient to reject outright. A brand-new agent with
    zero transaction history scores low for the same reason a first-time
    credit applicant has no credit score — absence of history is not
    evidence of guilt, it's the cold-start problem. Reject is reserved for
    a low score *combined with* an actual adverse record (a real dispute
    or confirmed-fraud rate on file); an unproven-but-clean agent gets
    routed to a human via step-up instead, which is the appropriately
    cautious middle ground.
    """

    if not verification.passed:
        return Decision.REJECT, 0.97

    if policy.hard_block:
        return Decision.REJECT, 0.95

    prior_fraud_rate = reputation.features.get("prior_fraud_rate", 0.0)
    has_adverse_history = prior_fraud_rate > 0.0 or reputation.prior_dispute_rate > 0.15

    if reputation.score < REPUTATION_REJECT_BELOW and has_adverse_history:
        return Decision.REJECT, round(0.7 + (REPUTATION_REJECT_BELOW - reputation.score), 2)

    needs_step_up = (
        policy.requires_step_up_by_policy
        or not policy.within_velocity_cap
        or reputation.score < REPUTATION_STEP_UP_BELOW
    )
    if needs_step_up:
        distance = abs(reputation.score - REPUTATION_STEP_UP_BELOW)
        return Decision.STEP_UP, round(min(0.9, 0.55 + distance), 2)

    confidence = round(min(0.99, 0.6 + (reputation.score - REPUTATION_STEP_UP_BELOW)), 2)
    return Decision.APPROVE, confidence


def _template_rationale(
    mandate: NormalizedMandate,
    verification: VerificationResult,
    reputation: ReputationResult,
    policy: PolicyEvaluation,
    decision: Decision,
) -> str:
    """Deterministic, human-readable explanation. Used whenever no LLM key
    is configured, and always available as a fallback if an LLM call fails
    — a rationale must never be empty just because an API had a bad day."""

    lines = [
        f"Agent '{mandate.agent_id}' ({mandate.agent_platform}) requested a "
        f"{mandate.amount_minor_units / 100:.2f} {mandate.currency} order in category "
        f"'{mandate.category}' from merchant '{mandate.merchant_id}'.",
        f"Verification: {'passed' if verification.passed else 'FAILED'} — {'; '.join(verification.reasons)}.",
        f"Reputation score: {reputation.score:.2f} "
        f"(prior orders: {reputation.prior_transaction_count}, dispute rate: {reputation.prior_dispute_rate:.2%}).",
        f"Policy: {'; '.join(policy.rule_hits)}.",
    ]
    closing = {
        Decision.APPROVE: "Net decision: APPROVE — verification passed, policy clear, reputation adequate.",
        Decision.STEP_UP: "Net decision: STEP UP — one or more soft signals warrant explicit merchant/human approval before this proceeds.",
        Decision.REJECT: "Net decision: REJECT — a hard verification or policy failure makes this order unsafe to honor automatically.",
    }[decision]
    lines.append(closing)
    return " ".join(lines)


def _llm_rationale(
    mandate: NormalizedMandate,
    verification: VerificationResult,
    reputation: ReputationResult,
    policy: PolicyEvaluation,
    decision: Decision,
) -> str | None:
    """Optional: if ANTHROPIC_API_KEY is set, ask Claude to write a sharper,
    more merchant-friendly rationale over the *same* already-decided
    outcome. Returns None on any failure so the caller falls back to the
    template — a demo must never crash because a network call timed out."""

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        prompt = (
            "You are writing a one-paragraph, merchant-facing explanation for an "
            "already-made agent-checkout authorization decision. Do not change the "
            "decision or invent facts beyond what is given. Be concise and concrete.\n\n"
            f"Decision: {decision.value}\n"
            f"Mandate: agent={mandate.agent_id} platform={mandate.agent_platform} "
            f"amount={mandate.amount_minor_units/100:.2f} {mandate.currency} category={mandate.category}\n"
            f"Verification passed: {verification.passed} ({'; '.join(verification.reasons)})\n"
            f"Reputation score: {reputation.score:.2f}, prior orders: {reputation.prior_transaction_count}, "
            f"dispute rate: {reputation.prior_dispute_rate:.2%}\n"
            f"Policy rule hits: {'; '.join(policy.rule_hits)}\n"
        )
        message = client.messages.create(
            model="claude-3-5-haiku-latest",
            max_tokens=220,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(block.text for block in message.content if hasattr(block, "text")).strip()
        return text or None
    except Exception:
        return None


def generate_rationale(
    mandate: NormalizedMandate,
    verification: VerificationResult,
    reputation: ReputationResult,
    policy: PolicyEvaluation,
    decision: Decision,
) -> str:
    llm_text = _llm_rationale(mandate, verification, reputation, policy, decision)
    if llm_text:
        return llm_text
    return _template_rationale(mandate, verification, reputation, policy, decision)
