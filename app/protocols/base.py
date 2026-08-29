"""Protocol adapter contract.

Every inbound agent-commerce protocol implements `to_normalized_mandate`,
turning its own wire format into the single canonical `NormalizedMandate`
the rest of the gateway operates on. This is the seam that lets Mandate
Gateway add a new protocol (a hypothetical Mastercard Agent Pay adapter,
say) without touching verification, reputation, policy, or reasoning.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.schemas import NormalizedMandate


class ProtocolAdapter(ABC):
    name: str

    @abstractmethod
    def to_normalized_mandate(self, raw_payload: dict[str, Any]) -> NormalizedMandate:
        ...
