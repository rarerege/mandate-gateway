"""Deterministic policy evaluation.

This is the merchant's actual, auditable rulebook — plain YAML, no LLM in
the loop. Everything here is intentionally boring and easy to unit test:
an authorization boundary should never depend on a language model having a
good day.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from app.schemas import NormalizedMandate, PolicyEvaluation

DEFAULT_POLICY_PATH = Path(__file__).resolve().parent / "merchant_policy.yaml"


class PolicyEngine:
    def __init__(self, policy_path: Path = DEFAULT_POLICY_PATH):
        self.policy_path = policy_path
        self.policy = self._load()

    def _load(self) -> dict:
        with open(self.policy_path) as f:
            return yaml.safe_load(f)

    def reload(self) -> None:
        self.policy = self._load()

    def evaluate(self, mandate: NormalizedMandate, orders_last_hour: int) -> PolicyEvaluation:
        rule_hits: list[str] = []

        allowed = mandate.category in self.policy["allowed_categories"]
        denied = mandate.category in self.policy.get("denied_categories", [])
        allowed_category = allowed and not denied
        if denied:
            rule_hits.append(f"category '{mandate.category}' is on the merchant deny-list")
        elif not allowed:
            rule_hits.append(f"category '{mandate.category}' is not on the merchant allow-list")

        cap = self.policy["amount_caps_minor_units"].get(
            mandate.category, self.policy["amount_caps_minor_units"]["default"]
        )
        within_amount_cap = mandate.amount_minor_units <= cap
        if not within_amount_cap:
            rule_hits.append(
                f"amount {mandate.amount_minor_units} exceeds cap {cap} for category '{mandate.category}'"
            )

        velocity_cap = self.policy["velocity_cap_per_hour"]
        within_velocity_cap = orders_last_hour < velocity_cap
        if not within_velocity_cap:
            rule_hits.append(
                f"agent has placed {orders_last_hour} orders in the last hour (cap: {velocity_cap})"
            )

        step_up_threshold = self.policy["step_up_amount_threshold_minor_units"]
        is_trusted_platform = mandate.agent_platform in self.policy.get("trusted_agent_platforms", [])
        requires_step_up = mandate.amount_minor_units >= step_up_threshold and not is_trusted_platform
        if requires_step_up:
            rule_hits.append(
                f"amount {mandate.amount_minor_units} >= step-up threshold {step_up_threshold} "
                f"for non-trusted platform '{mandate.agent_platform}'"
            )

        if not rule_hits:
            rule_hits.append("no policy rules triggered")

        return PolicyEvaluation(
            allowed_category=allowed_category,
            within_amount_cap=within_amount_cap,
            within_velocity_cap=within_velocity_cap,
            requires_step_up_by_policy=requires_step_up,
            rule_hits=rule_hits,
        )
