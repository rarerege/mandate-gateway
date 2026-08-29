"""The trained ML core of the reputation service.

A small logistic-regression classifier over hand-engineered features
predicts P(this order, from this agent, is legitimate). This is the
"traditional ML" component the report calls for: the LLM downstream
narrates this number, it does not compute it.
"""
from __future__ import annotations

import math
from pathlib import Path

import joblib
import numpy as np

from app.reputation.store import AgentSnapshot
from app.schemas import NormalizedMandate, ReputationResult

MODEL_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "reputation_model.joblib"

FEATURE_NAMES = [
    "log_prior_transactions",
    "prior_dispute_rate",
    "prior_fraud_rate",
    "log_account_age_days",
    "orders_last_hour",
    "excess_log_amount",
    "is_new_agent",
    "high_velocity_flag",
]

HIGH_RISK_CATEGORIES = {"electronics", "gift_cards", "crypto", "jewellery"}

# Reference point for "a typical order's log-amount" — only the amount above
# this reference counts against an agent. This mirrors how a real risk team
# would reason ("is this unusually large for this kind of order?") rather
# than penalizing every order for its raw size, and it must match the
# reference used when generating training labels in train_model.py.
REFERENCE_LOG_AMOUNT = 10.8


def build_features(mandate: NormalizedMandate, snapshot: AgentSnapshot) -> np.ndarray:
    log_prior_tx = math.log1p(snapshot.prior_transaction_count)
    dispute_rate = snapshot.prior_dispute_rate
    fraud_rate = (
        snapshot.prior_confirmed_fraud_count / snapshot.prior_transaction_count
        if snapshot.prior_transaction_count
        else 0.0
    )
    log_age = math.log1p(snapshot.account_age_days)
    velocity = float(snapshot.orders_last_hour)
    excess_log_amount = max(0.0, math.log1p(mandate.amount_minor_units) - REFERENCE_LOG_AMOUNT)
    is_new = 1.0 if snapshot.account_age_days < 3 else 0.0
    high_velocity = 1.0 if snapshot.orders_last_hour >= 5 else 0.0

    return np.array(
        [[log_prior_tx, dispute_rate, fraud_rate, log_age, velocity, excess_log_amount, is_new, high_velocity]]
    )


class ReputationModel:
    def __init__(self, model=None):
        self._model = model

    @classmethod
    def load(cls) -> "ReputationModel":
        if not MODEL_PATH.exists():
            raise FileNotFoundError(
                f"No trained model at {MODEL_PATH}. Run `python -m app.reputation.train_model` first."
            )
        return cls(model=joblib.load(MODEL_PATH))

    def score(self, mandate: NormalizedMandate, snapshot: AgentSnapshot) -> ReputationResult:
        features = build_features(mandate, snapshot)
        proba = float(self._model.predict_proba(features)[0][1])
        return ReputationResult(
            agent_id=mandate.agent_id,
            score=proba,
            features=dict(zip(FEATURE_NAMES, features[0].tolist())),
            prior_transaction_count=snapshot.prior_transaction_count,
            prior_dispute_rate=snapshot.prior_dispute_rate,
        )
