from __future__ import annotations

from app.protocols.registry import get_adapter
from app.schemas import SourceProtocol
from app.verification.signer import generate_keypair
from app.verification.trust_roots import TrustRoot, TrustRootRegistry
from app.verification.verifier import verify_mandate
from scripts.mandate_factory import build_ap2_payload


def _fresh_registry_and_key():
    registry = TrustRootRegistry()
    private_key, public_key = generate_keypair()
    key_id = "test-key-1"
    registry.register(TrustRoot(key_id=key_id, platform="google-gemini", public_key=public_key))
    return registry, key_id, private_key


def test_valid_mandate_passes_all_checks():
    registry, key_id, private_key = _fresh_registry_and_key()
    payload = build_ap2_payload(
        agent_id="agent-x", agent_platform="google-gemini", merchant_id="m1",
        category="groceries", amount_minor_units=1000, key_id=key_id, private_key=private_key,
    )
    mandate = get_adapter(SourceProtocol.AP2).to_normalized_mandate(payload)
    result = verify_mandate(mandate, registry)
    assert result.passed
    assert result.signature_valid and result.not_expired and result.not_replayed and result.trust_root_known


def test_tampered_signature_fails():
    registry, key_id, private_key = _fresh_registry_and_key()
    payload = build_ap2_payload(
        agent_id="agent-x", agent_platform="google-gemini", merchant_id="m1",
        category="groceries", amount_minor_units=1000, key_id=key_id, private_key=private_key,
        tamper_signature=True,
    )
    mandate = get_adapter(SourceProtocol.AP2).to_normalized_mandate(payload)
    result = verify_mandate(mandate, registry)
    assert not result.passed
    assert not result.signature_valid


def test_expired_mandate_fails():
    registry, key_id, private_key = _fresh_registry_and_key()
    payload = build_ap2_payload(
        agent_id="agent-x", agent_platform="google-gemini", merchant_id="m1",
        category="groceries", amount_minor_units=1000, key_id=key_id, private_key=private_key,
        ttl_minutes=-1,
    )
    mandate = get_adapter(SourceProtocol.AP2).to_normalized_mandate(payload)
    result = verify_mandate(mandate, registry)
    assert not result.passed
    assert not result.not_expired


def test_replayed_nonce_fails_on_second_use():
    registry, key_id, private_key = _fresh_registry_and_key()
    payload = build_ap2_payload(
        agent_id="agent-x", agent_platform="google-gemini", merchant_id="m1",
        category="groceries", amount_minor_units=1000, key_id=key_id, private_key=private_key,
    )
    mandate = get_adapter(SourceProtocol.AP2).to_normalized_mandate(payload)

    first = verify_mandate(mandate, registry)
    second = verify_mandate(mandate, registry)

    assert first.not_replayed
    assert not second.not_replayed
    assert not second.passed


def test_unknown_signing_key_fails():
    registry = TrustRootRegistry()  # empty — nothing registered
    _, key_id, private_key = _fresh_registry_and_key()
    payload = build_ap2_payload(
        agent_id="agent-x", agent_platform="google-gemini", merchant_id="m1",
        category="groceries", amount_minor_units=1000, key_id=key_id, private_key=private_key,
    )
    mandate = get_adapter(SourceProtocol.AP2).to_normalized_mandate(payload)
    result = verify_mandate(mandate, registry)
    assert not result.passed
    assert not result.trust_root_known


def test_relabelled_platform_after_signing_fails_signature_check():
    """agent_platform is part of the signed bytes specifically so it can't
    be changed in flight after signing without invalidating the signature —
    e.g. a relay/MITM trying to relabel which platform an already-signed
    mandate claims to be from."""
    registry, key_id, private_key = _fresh_registry_and_key()  # key_id registered to google-gemini
    payload = build_ap2_payload(
        agent_id="agent-x", agent_platform="google-gemini", merchant_id="m1",
        category="groceries", amount_minor_units=1000, key_id=key_id, private_key=private_key,
    )
    payload["agent"]["platform"] = "openai-chatgpt"  # tampered post-signing, signature untouched
    mandate = get_adapter(SourceProtocol.AP2).to_normalized_mandate(payload)
    result = verify_mandate(mandate, registry)
    assert not result.passed
    assert not result.signature_valid


def test_agent_lying_about_its_own_platform_fails_trust_root_cross_check():
    """A different attack from the one above: the agent has a perfectly
    real, validly-registered signing key and signs honestly over its own
    (false) platform claim. The signature is internally consistent, so
    only cross-checking the claim against what the trust registry actually
    has that key_id registered to can catch it."""
    registry = TrustRootRegistry()
    private_key, public_key = generate_keypair()
    key_id = "test-key-openai"
    registry.register(TrustRoot(key_id=key_id, platform="openai-chatgpt", public_key=public_key))

    payload = build_ap2_payload(
        agent_id="agent-x", agent_platform="google-gemini",  # false: this key is registered to openai-chatgpt
        merchant_id="m1", category="groceries", amount_minor_units=1000,
        key_id=key_id, private_key=private_key,
    )
    mandate = get_adapter(SourceProtocol.AP2).to_normalized_mandate(payload)
    result = verify_mandate(mandate, registry)
    assert result.signature_valid  # the signature itself is genuinely valid...
    assert not result.platform_matches_trust_root  # ...but the platform claim is a lie
    assert not result.passed
