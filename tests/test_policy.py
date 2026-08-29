from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.policy.engine import PolicyEngine
from app.schemas import NormalizedMandate, SourceProtocol


def _mandate(**overrides) -> NormalizedMandate:
    now = datetime.now(timezone.utc)
    defaults = dict(
        mandate_id="m1",
        source_protocol=SourceProtocol.AP2,
        agent_id="agent-1",
        agent_platform="unknown-platform",
        user_reference="u1",
        merchant_id="merchant_demo_001",
        category="groceries",
        amount_minor_units=10000,
        currency="INR",
        items_summary="test",
        issued_at=now,
        expires_at=now + timedelta(minutes=10),
        nonce="n1",
        signature="sig",
        signing_key_id="key1",
    )
    defaults.update(overrides)
    return NormalizedMandate(**defaults)


def test_denied_category_blocks():
    engine = PolicyEngine()
    result = engine.evaluate(_mandate(category="gift_cards"), orders_last_hour=0)
    assert not result.allowed_category
    assert result.hard_block


def test_over_amount_cap_blocks():
    engine = PolicyEngine()
    result = engine.evaluate(_mandate(category="groceries", amount_minor_units=10_000_000), orders_last_hour=0)
    assert not result.within_amount_cap
    assert result.hard_block


def test_within_policy_allows():
    engine = PolicyEngine()
    result = engine.evaluate(_mandate(category="groceries", amount_minor_units=10000), orders_last_hour=0)
    assert result.allowed_category
    assert result.within_amount_cap
    assert not result.hard_block


def test_velocity_cap_triggers_step_up_not_hard_block():
    engine = PolicyEngine()
    result = engine.evaluate(_mandate(category="groceries", amount_minor_units=10000), orders_last_hour=10)
    assert not result.within_velocity_cap
    assert not result.hard_block  # velocity alone must not be a hard reject


def test_large_amount_from_untrusted_platform_requires_step_up():
    engine = PolicyEngine()
    result = engine.evaluate(
        _mandate(category="electronics", amount_minor_units=400000, agent_platform="unknown-platform"),
        orders_last_hour=0,
    )
    assert result.requires_step_up_by_policy


def test_large_amount_from_trusted_platform_skips_step_up():
    engine = PolicyEngine()
    result = engine.evaluate(
        _mandate(category="electronics", amount_minor_units=400000, agent_platform="google-gemini"),
        orders_last_hour=0,
    )
    assert not result.requires_step_up_by_policy
