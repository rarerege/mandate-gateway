"""Agent history store: the only source of truth for "how has this agent
behaved before." Backed by SQLite so it survives across process restarts
and is directly queryable/auditable — not an in-memory dict."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.db import get_conn

VELOCITY_WINDOW = timedelta(hours=1)


@dataclass
class AgentSnapshot:
    agent_id: str
    agent_platform: str
    account_age_days: int
    prior_transaction_count: int
    prior_dispute_count: int
    prior_confirmed_fraud_count: int
    orders_last_hour: int

    @property
    def prior_dispute_rate(self) -> float:
        if self.prior_transaction_count == 0:
            return 0.0
        return self.prior_dispute_count / self.prior_transaction_count


def get_or_create_agent(
    agent_id: str, agent_platform: str, account_age_days: int = 0, now: datetime | None = None
) -> AgentSnapshot:
    now = now or datetime.now(timezone.utc)
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM agent_history WHERE agent_id = ?", (agent_id,)
        ).fetchone()
        if row is None:
            conn.execute(
                """INSERT INTO agent_history
                   (agent_id, agent_platform, account_age_days, last_seen_at)
                   VALUES (?, ?, ?, ?)""",
                (agent_id, agent_platform, account_age_days, now.isoformat()),
            )
            row = conn.execute(
                "SELECT * FROM agent_history WHERE agent_id = ?", (agent_id,)
            ).fetchone()
        orders_last_hour = _velocity(conn, agent_id, now)
        return AgentSnapshot(
            agent_id=row["agent_id"],
            agent_platform=row["agent_platform"],
            account_age_days=row["account_age_days"],
            prior_transaction_count=row["prior_transaction_count"],
            prior_dispute_count=row["prior_dispute_count"],
            prior_confirmed_fraud_count=row["prior_confirmed_fraud_count"],
            orders_last_hour=orders_last_hour,
        )


def _velocity(conn, agent_id: str, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    cutoff = (now - VELOCITY_WINDOW).isoformat()
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM order_events WHERE agent_id = ? AND occurred_at > ?",
        (agent_id, cutoff),
    ).fetchone()
    return row["n"]


@dataclass
class PlatformBurstSnapshot:
    agent_platform: str
    merchant_id: str
    distinct_agents_last_hour: int
    total_orders_last_hour: int


def get_platform_burst(
    agent_platform: str, merchant_id: str, now: datetime | None = None
) -> PlatformBurstSnapshot:
    """The signal per-agent velocity structurally cannot see: many
    *distinct* agent identities on the same platform hitting the same
    merchant in a short window. Any single one of those agents can look
    completely unremarkable — one order, no history to be suspicious about
    — while the platform-level pattern is exactly what a coordinated ring
    using disposable agent identities looks like. This is a merchant-scoped
    signal (not a global agent-reputation one), so it lives here as its own
    query rather than folded into AgentSnapshot."""
    now = now or datetime.now(timezone.utc)
    cutoff = (now - VELOCITY_WINDOW).isoformat()
    with get_conn() as conn:
        row = conn.execute(
            """SELECT COUNT(DISTINCT agent_id) AS distinct_agents, COUNT(*) AS total
               FROM order_events
               WHERE agent_platform = ? AND merchant_id = ? AND occurred_at > ?""",
            (agent_platform, merchant_id, cutoff),
        ).fetchone()
    return PlatformBurstSnapshot(
        agent_platform=agent_platform,
        merchant_id=merchant_id,
        distinct_agents_last_hour=row["distinct_agents"],
        total_orders_last_hour=row["total"],
    )


def record_order_event(
    agent_id: str, agent_platform: str, merchant_id: str, now: datetime | None = None
) -> None:
    now = now or datetime.now(timezone.utc)
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO order_events (agent_id, agent_platform, merchant_id, occurred_at)
               VALUES (?, ?, ?, ?)""",
            (agent_id, agent_platform, merchant_id, now.isoformat()),
        )
        conn.execute(
            """UPDATE agent_history
               SET prior_transaction_count = prior_transaction_count + 1,
                   last_seen_at = ?
               WHERE agent_id = ?""",
            (now.isoformat(), agent_id),
        )


def seed_agent_stats(
    agent_id: str,
    agent_platform: str,
    account_age_days: int,
    prior_transaction_count: int,
    prior_dispute_count: int,
    prior_confirmed_fraud_count: int,
) -> None:
    """Directly sets an agent's history. Used only by the demo/eval
    scripts to construct realistic populations (a brand-new agent, a
    long-trusted one, a ring with a real dispute history) without having
    to replay hundreds of real transactions through the pipeline first."""
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO agent_history
                   (agent_id, agent_platform, account_age_days, prior_transaction_count,
                    prior_dispute_count, prior_confirmed_fraud_count, last_seen_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(agent_id) DO UPDATE SET
                    agent_platform=excluded.agent_platform,
                    account_age_days=excluded.account_age_days,
                    prior_transaction_count=excluded.prior_transaction_count,
                    prior_dispute_count=excluded.prior_dispute_count,
                    prior_confirmed_fraud_count=excluded.prior_confirmed_fraud_count,
                    last_seen_at=excluded.last_seen_at
            """,
            (
                agent_id,
                agent_platform,
                account_age_days,
                prior_transaction_count,
                prior_dispute_count,
                prior_confirmed_fraud_count,
                datetime.now(timezone.utc).isoformat(),
            ),
        )


def record_outcome(agent_id: str, was_legitimate: bool) -> None:
    with get_conn() as conn:
        if was_legitimate:
            return
        conn.execute(
            """UPDATE agent_history
               SET prior_dispute_count = prior_dispute_count + 1,
                   prior_confirmed_fraud_count = prior_confirmed_fraud_count + 1
               WHERE agent_id = ?""",
            (agent_id,),
        )
