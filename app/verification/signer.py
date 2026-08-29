"""Keypair generation + signing utilities.

These exist so the demo can *issue* plausible AP2/ACP/UPI-agentic mandates
(including deliberately broken ones for the eval set) without needing a
live connection to OpenAI, Google, or NPCI. The verifier in this package
does not import from here — it only ever sees a public key from the trust
root registry, which is the property that makes the security story real:
verification cannot be satisfied just because the same process signed the
payload.
"""
from __future__ import annotations

import base64

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives import serialization


def generate_keypair() -> tuple[Ed25519PrivateKey, Ed25519PublicKey]:
    private_key = Ed25519PrivateKey.generate()
    return private_key, private_key.public_key()


def sign(private_key: Ed25519PrivateKey, payload: bytes) -> str:
    signature = private_key.sign(payload)
    return base64.b64encode(signature).decode("ascii")


def public_key_to_hex(public_key: Ed25519PublicKey) -> str:
    raw = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return raw.hex()
