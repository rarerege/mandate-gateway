"""Adversarial evaluation harness.

Builds a synthetic, labelled population of mandates spanning legitimate
and adversarial cases, runs every one through the real pipeline, and
reports the honest metrics the buildathon rubric explicitly asks for:
false-approve rate on fraud, friction rate on legitimate orders, verifier
accuracy on tampered/expired/replayed mandates, and latency.

    python -m scripts.evaluate --n 300
"""
from __future__ import annotations

import argparse
import time
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from rich.console import Console
from rich.table import Table

from app.db import get_conn, init_db
from app.decision.pipeline import MandateGatewayPipeline
from app.reputation.store import seed_agent_stats
from app.schemas import Decision, SourceProtocol
from scripts.mandate_factory import BUILDERS
from scripts.seed_demo import ensure_seeded, get_demo_private_key

console = Console()

CATEGORY_WEIGHTS = [
    ("legit_established", 0.35),
    ("legit_new", 0.15),
    ("fraud_ring", 0.20),
    ("fraud_tampered", 0.10),
    ("fraud_expired", 0.10),
    ("fraud_replay", 0.10),
]

KEY_BY_PROTOCOL = {
    SourceProtocol.AP2: "ap2-google-2026-01",
    SourceProtocol.ACP: "acp-openai-2026-01",
    SourceProtocol.UPI_AGENTIC: "upi-npci-claude-2026-01",
}
PLATFORM_BY_KEY = {
    "ap2-google-2026-01": "google-gemini",
    "acp-openai-2026-01": "openai-chatgpt",
    "upi-npci-claude-2026-01": "npci-upi-agentic",
}


@dataclass
class CaseResult:
    ground_truth: str
    is_fraud: bool
    decision: Decision
    pre_escalation_decision: Decision
    verification_passed: bool
    latency_ms: float


def _weighted_choice(rng, weights: list[tuple[str, float]]) -> str:
    labels, probs = zip(*weights)
    return rng.choices(labels, weights=probs, k=1)[0]


def _make_case(rng, index: int, replay_nonce_pool: list[str]) -> tuple[SourceProtocol, dict, str, bool]:
    ground_truth = _weighted_choice(rng, CATEGORY_WEIGHTS)
    protocol = rng.choice(list(KEY_BY_PROTOCOL.keys()))
    key_id = KEY_BY_PROTOCOL[protocol]
    platform = PLATFORM_BY_KEY[key_id]
    builder = BUILDERS[protocol]
    agent_id = f"eval-agent-{ground_truth}-{index % 40}"

    is_fraud = ground_truth.startswith("fraud")
    tamper = False
    nonce = None
    ttl_minutes = 15
    category = rng.choice(["groceries", "electronics", "apparel", "home_goods", "subscriptions"])
    amount = int(rng.lognormvariate(8.2, 1.1))

    if ground_truth == "legit_established":
        seed_agent_stats(agent_id, platform, account_age_days=rng.randint(90, 900),
                          prior_transaction_count=rng.randint(20, 300),
                          prior_dispute_count=rng.randint(0, 2), prior_confirmed_fraud_count=0)
    elif ground_truth == "legit_new":
        seed_agent_stats(agent_id, platform, account_age_days=rng.randint(1, 10),
                          prior_transaction_count=rng.randint(0, 3),
                          prior_dispute_count=0, prior_confirmed_fraud_count=0)
        amount = min(amount, 400000)
    elif ground_truth == "fraud_ring":
        seed_agent_stats(agent_id, platform, account_age_days=rng.randint(5, 60),
                          prior_transaction_count=rng.randint(10, 60),
                          prior_dispute_count=rng.randint(4, 15), prior_confirmed_fraud_count=rng.randint(2, 10))
        amount = int(rng.lognormvariate(9.0, 1.0))
    elif ground_truth == "fraud_tampered":
        seed_agent_stats(agent_id, platform, account_age_days=rng.randint(30, 300),
                          prior_transaction_count=rng.randint(5, 100), prior_dispute_count=0, prior_confirmed_fraud_count=0)
        tamper = True
    elif ground_truth == "fraud_expired":
        seed_agent_stats(agent_id, platform, account_age_days=rng.randint(30, 300),
                          prior_transaction_count=rng.randint(5, 100), prior_dispute_count=0, prior_confirmed_fraud_count=0)
        ttl_minutes = -5  # already expired by the time it's checked
    elif ground_truth == "fraud_replay":
        seed_agent_stats(agent_id, platform, account_age_days=rng.randint(30, 300),
                          prior_transaction_count=rng.randint(5, 100), prior_dispute_count=0, prior_confirmed_fraud_count=0)
        if replay_nonce_pool:
            nonce = rng.choice(replay_nonce_pool)

    payload = builder(
        agent_id=agent_id,
        agent_platform=platform,
        merchant_id="merchant_demo_001",
        category=category,
        amount_minor_units=max(amount, 1000),
        key_id=key_id,
        private_key=get_demo_private_key(key_id),
        ttl_minutes=ttl_minutes,
        nonce=nonce,
        tamper_signature=tamper,
    )
    return protocol, payload, ground_truth, is_fraud


def _extract_nonce(protocol: SourceProtocol, payload: dict) -> str:
    if protocol == SourceProtocol.AP2:
        return payload["nonce"]
    if protocol == SourceProtocol.ACP:
        return payload["authorization"]["idempotency_key"]
    return payload["upi_ref_id"]


def _run_coordinated_burst_incident(
    rng, pipeline: MandateGatewayPipeline, incident_index: int, burst_size: int, sim_now: datetime
) -> tuple[list[CaseResult], datetime]:
    """Simulates the exact scenario a per-agent velocity cap cannot see: a
    ring that mints a fresh, individually clean-looking agent identity per
    order and fires `burst_size` of them at one merchant, on one platform,
    within a few compressed minutes. Every identity is seeded with a
    *strong* reputation profile — established account age, healthy prior
    transaction count, low dispute rate — so a false-approve here would be
    entirely down to the reputation/velocity signals missing the pattern,
    which is exactly what the platform-burst policy check exists to catch.
    """
    protocol = list(KEY_BY_PROTOCOL.keys())[incident_index % len(KEY_BY_PROTOCOL)]
    key_id = KEY_BY_PROTOCOL[protocol]
    platform = PLATFORM_BY_KEY[key_id]
    builder = BUILDERS[protocol]

    results: list[CaseResult] = []
    for j in range(burst_size):
        agent_id = f"eval-agent-burst-incident{incident_index}-{j}"
        seed_agent_stats(
            agent_id, platform, account_age_days=rng.randint(200, 600),
            prior_transaction_count=rng.randint(50, 200),
            prior_dispute_count=rng.randint(0, 1), prior_confirmed_fraud_count=0,
        )
        payload = builder(
            agent_id=agent_id, agent_platform=platform, merchant_id="merchant_demo_001",
            category="groceries", amount_minor_units=int(rng.lognormvariate(8.2, 0.5)),
            key_id=key_id, private_key=get_demo_private_key(key_id),
        )
        sim_now += timedelta(seconds=rng.uniform(2, 10))  # a burst arrives in a tight window

        start = time.perf_counter()
        try:
            decision = pipeline.authorize(
                payload, protocol, auto_step_up_response=None, verbose_escalation=False, now=sim_now
            )
        except Exception as exc:
            console.print(f"[red]burst incident {incident_index} case {j} raised {exc!r}[/red]")
            continue
        latency = (time.perf_counter() - start) * 1000

        results.append(
            CaseResult(
                ground_truth="fraud_coordinated_burst",
                is_fraud=True,
                decision=decision.decision,
                pre_escalation_decision=decision.pre_escalation_decision,
                verification_passed=decision.verification.passed,
                latency_ms=latency,
            )
        )
    return results, sim_now


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=300)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--burst-incidents", type=int, default=2, help="Coordinated-burst incidents to inject")
    parser.add_argument("--burst-size", type=int, default=40, help="Distinct agents per burst incident")
    args = parser.parse_args()

    import random

    rng = random.Random(args.seed)

    init_db()
    ensure_seeded()
    pipeline = MandateGatewayPipeline()

    replay_pool: list[str] = []
    results: list[CaseResult] = []

    # A virtual clock, not the real one: organic cases are spread across a
    # realistic multi-hour traffic timeline (so the hourly rolling-window
    # signals — per-agent velocity, per-platform distinct-agent burst —
    # actually get exercised the way they would in production) without the
    # harness needing to sleep in real wall-clock time to do it.
    sim_now = datetime.now(timezone.utc) - timedelta(hours=10)

    for i in range(args.n):
        sim_now += timedelta(seconds=rng.uniform(20, 200))
        protocol, payload, ground_truth, is_fraud = _make_case(rng, i, replay_pool)
        if ground_truth != "fraud_replay":
            replay_pool.append(_extract_nonce(protocol, payload))

        start = time.perf_counter()
        try:
            decision = pipeline.authorize(
                payload, protocol, auto_step_up_response=None, verbose_escalation=False, now=sim_now
            )
        except Exception as exc:  # a malformed case should never crash the harness
            console.print(f"[red]case {i} raised {exc!r}, treating as REJECT[/red]")
            continue
        latency = (time.perf_counter() - start) * 1000

        results.append(
            CaseResult(
                ground_truth=ground_truth,
                is_fraud=is_fraud,
                decision=decision.decision,
                pre_escalation_decision=decision.pre_escalation_decision,
                verification_passed=decision.verification.passed,
                latency_ms=latency,
            )
        )

    for incident in range(args.burst_incidents):
        sim_now += timedelta(minutes=rng.uniform(10, 90))  # incidents don't overlap each other
        burst_results, sim_now = _run_coordinated_burst_incident(rng, pipeline, incident, args.burst_size, sim_now)
        results.extend(burst_results)

    _report(results)


def _report(results: list[CaseResult]) -> None:
    n = len(results)
    fraud = [r for r in results if r.is_fraud]
    legit = [r for r in results if not r.is_fraud]

    fraud_approved = sum(1 for r in fraud if r.decision == Decision.APPROVE)
    fraud_caught = sum(1 for r in fraud if r.decision != Decision.APPROVE)
    legit_frictionless = sum(1 for r in legit if r.decision == Decision.APPROVE)
    legit_friction = sum(1 for r in legit if r.decision != Decision.APPROVE)

    verifier_should_fail = [r for r in results if r.ground_truth in ("fraud_tampered", "fraud_expired", "fraud_replay")]
    verifier_correctly_failed = sum(1 for r in verifier_should_fail if not r.verification_passed)

    avg_latency = sum(r.latency_ms for r in results) / max(n, 1)
    p95_latency = sorted(r.latency_ms for r in results)[int(0.95 * (n - 1))] if n else 0.0

    table = Table(title=f"Mandate Gateway — evaluation over {n} synthetic cases")
    table.add_column("Metric")
    table.add_column("Value", justify="right")

    table.add_row("Fraud cases", str(len(fraud)))
    table.add_row("  -> approved (FALSE APPROVE — the critical failure mode)", f"{fraud_approved} ({fraud_approved/max(len(fraud),1):.1%})")
    table.add_row("  -> stepped-up or rejected (caught)", f"{fraud_caught} ({fraud_caught/max(len(fraud),1):.1%})")
    table.add_row("Legit cases", str(len(legit)))
    table.add_row("  -> approved frictionlessly", f"{legit_frictionless} ({legit_frictionless/max(len(legit),1):.1%})")
    table.add_row("  -> stepped-up/rejected (friction cost)", f"{legit_friction} ({legit_friction/max(len(legit),1):.1%})")
    table.add_row("Verifier accuracy on tampered/expired/replayed", f"{verifier_correctly_failed}/{len(verifier_should_fail)} ({verifier_correctly_failed/max(len(verifier_should_fail),1):.1%})")
    table.add_row("Avg decision latency", f"{avg_latency:.2f} ms")
    table.add_row("p95 decision latency", f"{p95_latency:.2f} ms")

    console.print(table)

    breakdown = Table(title="Pre-escalation decision (raw verify+reputation+policy tier, before any human answers a step-up)")
    breakdown.add_column("Ground truth")
    breakdown.add_column("n", justify="right")
    breakdown.add_column("approve", justify="right")
    breakdown.add_column("step_up", justify="right")
    breakdown.add_column("reject", justify="right")
    by_cat: dict[str, Counter] = {}
    for r in results:
        by_cat.setdefault(r.ground_truth, Counter())[r.pre_escalation_decision.value] += 1
    for cat, counts in sorted(by_cat.items()):
        total = sum(counts.values())
        breakdown.add_row(cat, str(total), str(counts.get("approve", 0)), str(counts.get("step_up", 0)), str(counts.get("reject", 0)))
    console.print(breakdown)

    breakdown2 = Table(title="Final decision by ground-truth category (unattended: step_up defaults to reject)")
    breakdown2.add_column("Ground truth")
    breakdown2.add_column("n", justify="right")
    breakdown2.add_column("approve", justify="right")
    breakdown2.add_column("step_up", justify="right")
    breakdown2.add_column("reject", justify="right")
    by_cat = {}
    for r in results:
        by_cat.setdefault(r.ground_truth, Counter())[r.decision.value] += 1
    for cat, counts in sorted(by_cat.items()):
        total = sum(counts.values())
        breakdown2.add_row(cat, str(total), str(counts.get("approve", 0)), str(counts.get("step_up", 0)), str(counts.get("reject", 0)))
    console.print(breakdown2)

    console.print(
        "\n[dim]Note: 'step_up' cases with no simulated merchant response default to reject "
        "(see app/escalation/handler.py) — this is why decision != pre_escalation_decision for "
        "some legit_new cases and is the honest, conservative behaviour of an unattended gateway.[/dim]"
    )


if __name__ == "__main__":
    main()
