from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.reputation.model import ReputationModel
from app.reputation.store import get_or_create_agent, seed_agent_stats
from app.schemas import NormalizedMandate, SourceProtocol


def _mandate(amount=10000) -> NormalizedMandate:
    now = datetime.now(timezone.utc)
    return NormalizedMandate(
        mandate_id="m1", source_protocol=SourceProtocol.AP2, agent_id="agent-1",
        agent_platform="google-gemini", user_reference="u1", merchant_id="merchant_demo_001",
        category="groceries", amount_minor_units=amount, currency="INR", items_summary="test",
        issued_at=now, expires_at=now + timedelta(minutes=10), nonce="n1", signature="sig", signing_key_id="key1",
    )


@pytest.fixture(scope="module")
def model():
    try:
        return ReputationModel.load()
    except FileNotFoundError:
        pytest.skip("Run `python -m app.reputation.train_model` before the test suite.")


def test_established_clean_agent_scores_higher_than_fresh_bad_agent(model):
    seed_agent_stats("good-agent", "google-gemini", account_age_days=400,
                      prior_transaction_count=150, prior_dispute_count=1, prior_confirmed_fraud_count=0)
    seed_agent_stats("bad-agent", "openai-chatgpt", account_age_days=2,
                      prior_transaction_count=3, prior_dispute_count=2, prior_confirmed_fraud_count=2)

    good_snapshot = get_or_create_agent("good-agent", "google-gemini")
    bad_snapshot = get_or_create_agent("bad-agent", "openai-chatgpt")

    good_score = model.score(_mandate(), good_snapshot).score
    bad_score = model.score(_mandate(), bad_snapshot).score

    assert good_score > bad_score


def test_score_is_a_probability(model):
    snapshot = get_or_create_agent("some-agent", "google-gemini")
    result = model.score(_mandate(), snapshot)
    assert 0.0 <= result.score <= 1.0
