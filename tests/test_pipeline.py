from __future__ import annotations

import pytest

from app.decision.pipeline import MandateGatewayPipeline
from app.escalation.handler import StepUpResponse
from app.reputation.model import ReputationModel
from app.schemas import Decision, SourceProtocol
from scripts.mandate_factory import BUILDERS
from scripts.seed_demo import ensure_seeded, get_demo_private_key


@pytest.fixture()
def pipeline():
    try:
        ReputationModel.load()
    except FileNotFoundError:
        pytest.skip("Run `python -m app.reputation.train_model` before the test suite.")
    ensure_seeded()
    return MandateGatewayPipeline()


def test_trusted_agent_ordinary_order_is_approved(pipeline):
    key_id = "ap2-google-2026-01"
    payload = BUILDERS[SourceProtocol.AP2](
        agent_id="agent-longtrust-nova", agent_platform="google-gemini", merchant_id="merchant_demo_001",
        category="groceries", amount_minor_units=30000, key_id=key_id, private_key=get_demo_private_key(key_id),
    )
    result = pipeline.authorize(payload, SourceProtocol.AP2)
    assert result.decision == Decision.APPROVE
    assert result.verification.passed


def test_tampered_mandate_is_rejected_before_reputation_matters(pipeline):
    key_id = "ap2-google-2026-01"
    payload = BUILDERS[SourceProtocol.AP2](
        agent_id="agent-longtrust-nova", agent_platform="google-gemini", merchant_id="merchant_demo_001",
        category="groceries", amount_minor_units=30000, key_id=key_id, private_key=get_demo_private_key(key_id),
        tamper_signature=True,
    )
    result = pipeline.authorize(payload, SourceProtocol.AP2)
    assert result.decision == Decision.REJECT
    assert not result.verification.passed


def test_denied_category_is_rejected_even_for_good_agent(pipeline):
    key_id = "ap2-google-2026-01"
    payload = BUILDERS[SourceProtocol.AP2](
        agent_id="agent-longtrust-nova", agent_platform="google-gemini", merchant_id="merchant_demo_001",
        category="crypto", amount_minor_units=30000, key_id=key_id, private_key=get_demo_private_key(key_id),
    )
    result = pipeline.authorize(payload, SourceProtocol.AP2)
    assert result.decision == Decision.REJECT
    assert result.policy.hard_block


def test_step_up_can_be_approved_by_simulated_merchant(pipeline):
    key_id = "acp-openai-2026-01"
    payload = BUILDERS[SourceProtocol.ACP](
        agent_id="agent-newcomer-atlas", agent_platform="openai-chatgpt", merchant_id="merchant_demo_001",
        category="electronics", amount_minor_units=890000, key_id=key_id, private_key=get_demo_private_key(key_id),
    )
    result = pipeline.authorize(
        payload, SourceProtocol.ACP,
        auto_step_up_response=StepUpResponse(approved=True, responder="test-merchant"),
    )
    assert result.pre_escalation_decision == Decision.STEP_UP
    assert result.decision == Decision.APPROVE


def test_unattended_step_up_defaults_to_reject(pipeline):
    key_id = "acp-openai-2026-01"
    payload = BUILDERS[SourceProtocol.ACP](
        agent_id="agent-newcomer-atlas", agent_platform="openai-chatgpt", merchant_id="merchant_demo_001",
        category="electronics", amount_minor_units=890000, key_id=key_id, private_key=get_demo_private_key(key_id),
    )
    result = pipeline.authorize(payload, SourceProtocol.ACP, auto_step_up_response=None)
    assert result.pre_escalation_decision == Decision.STEP_UP
    assert result.decision == Decision.REJECT


def test_audit_hash_is_recorded_and_chain_stays_intact(pipeline):
    from app.audit.log import verify_chain_integrity

    key_id = "ap2-google-2026-01"
    payload = BUILDERS[SourceProtocol.AP2](
        agent_id="agent-longtrust-nova", agent_platform="google-gemini", merchant_id="merchant_demo_001",
        category="groceries", amount_minor_units=30000, key_id=key_id, private_key=get_demo_private_key(key_id),
    )
    result = pipeline.authorize(payload, SourceProtocol.AP2)
    assert result.audit_hash is not None

    ok, message = verify_chain_integrity()
    assert ok, message
