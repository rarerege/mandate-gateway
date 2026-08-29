"""Registry of known mandate-issuer public keys.

In production this would be a rotating, per-platform keyset fetched from
each protocol's discovery endpoint (AP2 and ACP both specify one). For the
hackathon build it's an in-memory registry seeded by scripts/seed_demo.py,
which is exactly the seam a real integration would replace.
"""
from __future__ import annotations

from dataclasses import dataclass

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


@dataclass
class TrustRoot:
    key_id: str
    platform: str
    public_key: Ed25519PublicKey


class TrustRootRegistry:
    def __init__(self) -> None:
        self._roots: dict[str, TrustRoot] = {}

    def register(self, root: TrustRoot) -> None:
        self._roots[root.key_id] = root

    def get(self, key_id: str) -> TrustRoot | None:
        return self._roots.get(key_id)

    def known(self, key_id: str) -> bool:
        return key_id in self._roots


# Process-wide singleton. seed_demo.py populates this at startup for the
# demo; a real deployment would hydrate it from persistent storage instead.
REGISTRY = TrustRootRegistry()
