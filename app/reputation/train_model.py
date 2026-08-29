"""Trains the reputation classifier on synthetic agent-behaviour data.

There is no real agent-fraud dataset to train on (this is a brand new
fraud surface — see the dossier's Part 3/4 research on why). So we
generate a synthetic population whose *labels* are produced by a latent
rule ("new account + high velocity + high amount => usually bad") plus
noise, then train a real classifier on the *features*, not the rule
itself. The point is to demonstrate a genuine train/eval pipeline with
held-out accuracy — not to claim the synthetic prior is production-grade.
Swapping in real chargeback-labelled data later requires no code changes
beyond this file.
"""
from __future__ import annotations

import math
from pathlib import Path

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, roc_auc_score
from sklearn.model_selection import train_test_split

from app.reputation.model import FEATURE_NAMES, MODEL_PATH, REFERENCE_LOG_AMOUNT

RNG = np.random.default_rng(seed=42)
N_SAMPLES = 6000


def _simulate_population(n: int) -> tuple[np.ndarray, np.ndarray]:
    prior_tx = RNG.integers(0, 500, size=n)
    account_age = RNG.integers(0, 1200, size=n)
    # dispute/fraud history correlates with each other and with youth of account
    base_bad_prior = RNG.beta(1.5, 20, size=n)
    dispute_rate = np.clip(base_bad_prior + RNG.normal(0, 0.02, size=n), 0, 1)
    fraud_rate = np.clip(dispute_rate * RNG.uniform(0.2, 0.8, size=n), 0, 1)
    # Amounts in minor units (paise): lognormal centered near a typical
    # ~INR 500 order, wide enough tail to cover everything from a small
    # top-up to a large electronics purchase.
    velocity = RNG.poisson(1.2, size=n) + (account_age < 5) * RNG.poisson(4, size=n)
    amount = np.exp(RNG.normal(10.8, 1.1, size=n)).astype(int)
    is_new = (account_age < 3).astype(float)
    high_velocity = (velocity >= 5).astype(float)

    log_prior_tx = np.log1p(prior_tx)
    log_age = np.log1p(account_age)
    excess_log_amount = np.clip(np.log1p(amount) - REFERENCE_LOG_AMOUNT, 0, None)

    features = np.column_stack(
        [log_prior_tx, dispute_rate, fraud_rate, log_age, velocity, excess_log_amount, is_new, high_velocity]
    )

    # Latent legitimacy score: more history & age => safer; disputes,
    # fraud history, freshness, velocity, and unusually large amounts => riskier.
    latent = (
        0.55 * log_prior_tx
        + 0.35 * log_age
        - 6.0 * dispute_rate
        - 9.0 * fraud_rate
        - 0.45 * is_new
        - 0.5 * high_velocity
        - 0.13 * excess_log_amount
        + RNG.normal(0, 0.6, size=n)
    )
    prob_legit = 1 / (1 + np.exp(-(latent + 0.4)))
    labels = RNG.binomial(1, prob_legit)
    return features, labels


def main() -> None:
    X, y = _simulate_population(N_SAMPLES)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, random_state=42, stratify=y
    )

    model = LogisticRegression(max_iter=1000, class_weight="balanced")
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    y_proba = model.predict_proba(X_test)[:, 1]

    print("=== Reputation model — held-out evaluation ===")
    print(classification_report(y_test, y_pred, target_names=["risky", "legit"]))
    print(f"ROC AUC: {roc_auc_score(y_test, y_proba):.4f}")
    print("Feature order:", FEATURE_NAMES)
    print("Coefficients:", dict(zip(FEATURE_NAMES, model.coef_[0].round(3).tolist())))

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, MODEL_PATH)
    print(f"\nSaved trained model to {MODEL_PATH}")


if __name__ == "__main__":
    main()
