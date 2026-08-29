"""The exact 4 scenarios described in the project pitch, run end-to-end
against the real pipeline (real signature verification, real trained
reputation model, real policy YAML). Run with:

    python -m scripts.run_demo_scenarios
"""
from __future__ import annotations

from rich.console import Console
from rich.panel import Panel

from app.db import init_db
from app.decision.pipeline import MandateGatewayPipeline
from app.escalation.handler import StepUpResponse
from app.schemas import SourceProtocol
from scripts.mandate_factory import BUILDERS
from scripts.seed_demo import ensure_seeded, get_demo_private_key

console = Console()


def _run_case(pipeline: MandateGatewayPipeline, title: str, protocol: SourceProtocol, payload: dict, auto_step_up=None) -> None:
    console.rule(f"[bold]{title}")
    result = pipeline.authorize(payload, protocol, auto_step_up_response=auto_step_up)
    color = {"approve": "green", "step_up": "yellow", "reject": "red"}[result.decision.value]
    console.print(
        Panel(
            f"[bold {color}]{result.decision.value.upper()}[/bold {color}]  "
            f"(confidence {result.confidence:.2f}, {result.latency_ms:.1f} ms)\n\n"
            f"{result.rationale}\n\n"
            f"[dim]audit hash: {result.audit_hash[:16]}...[/dim]",
            title=result.mandate_id,
        )
    )


def main() -> None:
    init_db()
    ensure_seeded()
    pipeline = MandateGatewayPipeline()

    # 1. Normal order from a long-trusted agent -> should APPROVE cleanly.
    key_id = "ap2-google-2026-01"
    payload = BUILDERS[SourceProtocol.AP2](
        agent_id="agent-longtrust-nova",
        agent_platform="google-gemini",
        merchant_id="merchant_demo_001",
        category="groceries",
        amount_minor_units=45000,  # ₹450
        key_id=key_id,
        private_key=get_demo_private_key(key_id),
    )
    _run_case(pipeline, "Scenario 1 — trusted agent, ordinary order", SourceProtocol.AP2, payload)

    # 2. Suspicious high-value order from a brand-new, unproven agent -> STEP_UP,
    #    and we script the merchant approving it on WhatsApp.
    key_id = "acp-openai-2026-01"
    payload = BUILDERS[SourceProtocol.ACP](
        agent_id="agent-newcomer-atlas",
        agent_platform="openai-chatgpt",
        merchant_id="merchant_demo_001",
        category="electronics",
        amount_minor_units=890000,  # ₹8,900
        key_id=key_id,
        private_key=get_demo_private_key(key_id),
    )
    _run_case(
        pipeline,
        "Scenario 2 — new agent, high-value order -> stepped up to merchant",
        SourceProtocol.ACP,
        payload,
        auto_step_up=StepUpResponse(approved=True, responder="merchant-owner", note="Recognized customer via WhatsApp, approved manually."),
    )

    # 3. Policy-violating order (denied category) from a known-bad agent -> REJECT.
    key_id = "acp-openai-2026-01"
    payload = BUILDERS[SourceProtocol.ACP](
        agent_id="agent-ringleader-vex",
        agent_platform="openai-chatgpt",
        merchant_id="merchant_demo_001",
        category="gift_cards",
        amount_minor_units=250000,
        key_id=key_id,
        private_key=get_demo_private_key(key_id),
    )
    _run_case(pipeline, "Scenario 3 — denied category from a poor-reputation agent", SourceProtocol.ACP, payload)

    # 4. Bonus — tampered signature on an otherwise-plausible order -> REJECT
    #    on verification alone, before reputation or policy are even consulted.
    key_id = "upi-npci-claude-2026-01"
    payload = BUILDERS[SourceProtocol.UPI_AGENTIC](
        agent_id="agent-npci-shopper-01",
        agent_platform="npci-upi-agentic",
        merchant_id="merchant_demo_001",
        category="subscriptions",
        amount_minor_units=19900,
        key_id=key_id,
        private_key=get_demo_private_key(key_id),
        tamper_signature=True,
    )
    _run_case(pipeline, "Scenario 4 (bonus) — tampered mandate signature", SourceProtocol.UPI_AGENTIC, payload)


if __name__ == "__main__":
    main()
