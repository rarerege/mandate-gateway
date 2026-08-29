# Mandate Gateway

**Merchant-side authorization and policy layer for agent-initiated checkouts.**
Built for the Razorpay AI Buildathon 2026 — Track 1, AI Growth & Agentic Commerce.

Every major payments network shipped a way for an AI agent to cryptographically prove a human authorized a purchase in 2025–2026: Google's [AP2](https://cloud.google.com/blog/products/ai-machine-learning/announcing-agents-to-payments-ap2-protocol), Stripe/OpenAI's [ACP](https://stripe.com/newsroom/news/stripe-openai-instant-checkout), Visa's Trusted Agent Protocol, and Razorpay's own agentic UPI work with NPCI and Claude. None of them ship the other half: **how does the merchant decide whether to actually honor an inbound agent order?** Mandate Gateway is that missing piece — it verifies the mandate, scores the agent, applies the merchant's own policy, and returns an explainable approve / step-up / reject decision with a full, tamper-evident audit trail.

See [`ARCHITECTURE.md`](./ARCHITECTURE.md) for the full technical design (component diagram, security model, what's real vs. mocked, known limitations) and [`PLAN.md`](./PLAN.md) for the build/submission plan.

## Quickstart

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Train the reputation classifier (prints a held-out precision/recall/ROC-AUC report)
python -m app.reputation.train_model

# Seed demo trust-root keys and a handful of demo agents (idempotent)
python -m scripts.seed_demo

# Run the 4 demo scenarios end-to-end against the real pipeline
python -m scripts.run_demo_scenarios

# Run the adversarial evaluation harness (300 synthetic cases by default)
python -m scripts.evaluate --n 300

# Run the test suite
python -m pytest -q

# Run the API
uvicorn app.main:app --reload
```

`data/reputation_model.joblib` and `data/demo_keys.json` are committed so the quickstart above works on a fresh clone without retraining or reseeding — the commands are still there so you can regenerate both from scratch and see exactly how.

No `ANTHROPIC_API_KEY`? Everything above still runs — the rationale generator falls back to a deterministic template. Set the env var to have Claude write the merchant-facing explanation instead (see `app/reasoning/reasoner.py`).

## API

| Endpoint | What it does |
|---|---|
| `POST /orders/authorize` | The main call: `{"protocol": "ap2"\|"acp"\|"upi_agentic", "payload": {...}}` → a full `GatewayDecision` |
| `GET /audit/{decision_id}` | Fetch one decision's full audit entry |
| `GET /audit-chain/verify` | Recomputes the entire hash chain and reports whether it's intact |
| `POST /outcomes` | Feed back ground truth (`was_legitimate`) for a past decision — updates agent reputation |
| `GET /policy` | Current merchant policy config |

## Project layout

```
app/
  schemas.py          # every data contract (NormalizedMandate, GatewayDecision, ...)
  protocols/           # AP2 / ACP / UPI-agentic adapters -> NormalizedMandate
  verification/        # Ed25519 signature + expiry + replay checks (the security boundary)
  reputation/           # sklearn classifier + SQLite-backed agent history store
  policy/               # YAML merchant policy + deterministic rule engine
  reasoning/            # decision boundary (pure function) + LLM-or-template rationale
  escalation/           # simulated WhatsApp-style step-up flow
  audit/                # hash-chained, tamper-evident decision log
  decision/pipeline.py  # orchestrates all of the above into one authorize() call
  main.py               # FastAPI surface
scripts/
  seed_demo.py           # trust-root keys + demo agent population
  run_demo_scenarios.py  # the 4 pitch-video scenarios, run for real
  evaluate.py             # adversarial eval harness with measured metrics
  mandate_factory.py      # builds real, signed AP2/ACP/UPI-agentic payloads for demos/tests
tests/                    # 24 tests across verification, policy, reputation, and the full pipeline
```

## The one architectural decision worth understanding before you read the code

The decision boundary (`app/reasoning/reasoner.py::decide_action`) is plain Python — verification result + reputation score + policy evaluation in, a decision out — with **zero LLM calls**. An LLM only ever runs afterward, to narrate a decision that has already been made, and the system runs correctly with no LLM configured at all. Putting a language model inside a payment-authorization boundary is a real prompt-injection surface (a hostile `items_summary` field could try to talk its way past a review); this system doesn't have that surface because the boundary isn't language-model-shaped in the first place.
