# Mandate Gateway — Technical Architecture

**Track:** AI Growth & Agentic Commerce — Razorpay AI Buildathon 2026
**One-liner:** A merchant-side authorization and policy layer for agent-initiated checkouts. When an AI shopping agent (via AP2, ACP, or UPI-agentic) tries to buy something from a merchant, Mandate Gateway decides — explainably, in real time — whether to honor it.

## 1. The problem this fills

Google's AP2, Stripe/OpenAI's ACP, Visa's Trusted Agent Protocol, and NPCI+Razorpay's agentic UPI all define how an AI agent proves a human authorized a purchase (cryptographically signed "mandates"). None of them — by their own authors' admission — define how a **merchant** decides whether to actually *honor* an inbound mandate: is this signature genuinely valid, has this agent identity misbehaved before, does this order fit what the merchant is willing to sell to an autonomous buyer. That decision layer is what this service is.

It deliberately does **not** duplicate Razorpay's existing, shipped Agentic Payments (buyer-side conversational checkout) — it is the missing merchant-side counterpart.

## 2. Component map

```
                          ┌────────────────────────────────────────────────────┐
                          │                 Mandate Gateway                     │
                          │                                                    │
  Inbound order  ───────► │  Protocol Adapter                                  │
  (AP2 / ACP /            │  (ap2_adapter / acp_adapter / upi_agentic_adapter) │
   UPI-agentic             │        │                                          │
   raw JSON)                │        ▼                                          │
                          │  NormalizedMandate (canonical, protocol-agnostic)  │
                          │        │                                          │
                          │        ▼                                          │
                          │  ┌──────────────┐   hard security boundary        │
                          │  │  Verifier    │   (Ed25519 signature, expiry,    │
                          │  │              │    replay/nonce, trust root)     │
                          │  └──────┬───────┘                                 │
                          │         │ pass/fail + reasons                     │
                          │         ▼                                        │
                          │  ┌──────────────┐   ┌──────────────┐             │
                          │  │ Reputation   │   │ Policy Engine │             │
                          │  │ (sklearn     │   │ (YAML rules,  │             │
                          │  │ logistic reg │   │ deterministic)│             │
                          │  │ over agent   │   └──────┬───────┘             │
                          │  │ history)     │          │                     │
                          │  └──────┬───────┘          │                     │
                          │         └─────────┬────────┘                     │
                          │                   ▼                              │
                          │         ┌──────────────────┐                     │
                          │         │ Decision Reasoner │  deterministic      │
                          │         │ (decide_action)   │  boundary +         │
                          │         └────────┬──────────┘  LLM-or-template    │
                          │                  │             rationale          │
                          │      approve/step_up/reject                      │
                          │                  │                                │
                          │                  ▼ (only if step_up)              │
                          │         ┌──────────────────┐                     │
                          │         │ Escalation        │  simulated          │
                          │         │ Handler           │  WhatsApp approval  │
                          │         └────────┬──────────┘                     │
                          │                  ▼                                │
                          │         ┌──────────────────┐                     │
                          │         │ Audit Log         │  hash-chained,      │
                          │         │ (SQLite)          │  tamper-evident     │
                          │         └────────┬──────────┘                     │
                          │                  ▼                                │
                          │         Agent history updated (learning loop)     │
                          └────────────────────────────────────────────────────┘
```

## 3. Why the pieces are shaped this way

**Protocol adapters (`app/protocols/`).** Each inbound protocol (AP2, ACP, UPI-agentic) has its own field names and nesting. An adapter's only job is to translate that into one `NormalizedMandate`. Nothing downstream — verification, reputation, policy, reasoning — ever branches on which protocol an order arrived through. Adding a fourth protocol (Visa TAP, Mastercard Agent Pay) means writing one adapter and registering it in `app/protocols/registry.py`; it touches nothing else.

**Verification (`app/verification/`) is the actual security boundary, and it is plain code, not an LLM call.** Four independent checks: Ed25519 signature over a canonical byte string, expiry, single-use nonce (replay), and a known trust root. This is deliberate: an authorization boundary should never depend on a language model's judgment on a given day, and it should never be talked around by adversarial text hidden inside an order's `items_summary` (a live prompt-injection surface if it ever reached an LLM before this check runs).

**Reputation (`app/reputation/`) is a small, real, trained classifier** (scikit-learn `LogisticRegression`), not a hand-tuned score. It is trained on a synthetic population (see §5 — there is no real agent-fraud dataset yet, because this fraud surface is new) and evaluated with a held-out precision/recall/ROC-AUC report every time it's retrained (`python -m app.reputation.train_model`). One explicit design decision worth calling out: **a low score alone never triggers an outright reject.** A brand-new agent with no transaction history scores low for the same reason a first-time credit applicant has no credit score — that's the cold-start problem, not evidence of guilt. Reject requires a low score **combined with** an actual adverse record (a real dispute or confirmed-fraud rate on file, see `app/reasoning/reasoner.py::decide_action`). An unproven-but-clean agent is routed to a human via step-up instead.

**Policy (`app/policy/`) is the merchant's own explicit, auditable configuration** — plain YAML, evaluated deterministically. Category allow/deny lists, per-category amount caps, a velocity cap, and a step-up amount threshold. This mirrors Razorpay's own published Agent Studio principle almost exactly: agents "do not create new discounts, modify pricing, or decide independently" — this gateway enforces a merchant's configuration, it does not invent one.

**Reasoning (`app/reasoning/`) is split into two halves on purpose.** `decide_action` is a pure function — verification + reputation + policy in, `(Decision, confidence)` out — unit-testable with no database, no model file, no network call. `generate_rationale` runs *after* the decision is already fixed: it either calls Claude (if `ANTHROPIC_API_KEY` is set) or falls back to a deterministic template to explain the decision in plain language. The LLM narrates; it never decides. This is the single most important architectural choice in the system and the one most worth defending in a judging conversation: putting an LLM in the authorization boundary of a payments system is a real security anti-pattern, not a simplification.

**Escalation (`app/escalation/`)** stands in for the WhatsApp step-up flow Razorpay's own Agent Studio principles describe. It logs what would be sent and accepts a scripted or default response. An unanswered step-up defaults to **reject** — never a silent approve — because a step-up nobody answers is not consent.

**Audit (`app/audit/`)** hash-chains every decision: each entry's hash covers its own payload plus the previous entry's hash, so editing or deleting a past decision breaks every hash after it. `verify_chain_integrity()` recomputes the whole chain and is exposed as both an API endpoint (`GET /audit-chain/verify`) and a test — "tamper-evident" is something you can check, not just assert in a README.

## 4. What's real vs. mocked (stated plainly, per the buildathon's own emphasis on honest reporting)

| Component | Real | Mocked / simplified |
|---|---|---|
| Signature scheme | Real Ed25519 keygen/sign/verify (`cryptography`) | Trust roots are a small in-process registry seeded by `scripts/seed_demo.py`, not a live fetch from each protocol's discovery endpoint |
| Protocol shapes | Structurally modeled on AP2/ACP's public specs and UPI conventions | Not full JSON-LD/Verifiable-Credential implementations — the shape is real, the crypto envelope around it is simplified |
| Reputation model | Real trained `sklearn` classifier, real held-out eval | Trained on synthetic labels (no real agent-fraud dataset exists yet — see §5) |
| Policy engine | Fully real, fully enforced | Single demo merchant config |
| Escalation | Real control flow, real default-to-reject-if-unanswered | "WhatsApp send" is a `print()`, not a live Business API call |
| Audit log | Real hash chain, real integrity check | Single-node SQLite, not distributed |
| LLM rationale | Real Claude call if `ANTHROPIC_API_KEY` is set | Falls back to a deterministic template with no key — the demo never depends on network access |

## 5. Why the reputation model is trained on synthetic data, honestly

There is no public agent-initiated-fraud dataset — this is a fraud surface that didn't exist before 2025/2026 agentic-commerce protocols. `app/reputation/train_model.py` generates a synthetic population where account age, transaction history, dispute/fraud history, order velocity, and order size jointly determine a *latent* legitimacy score (plus noise), then trains a real logistic regression on the resulting *features*, not the rule itself. The model is evaluated on a held-out split every time it trains, printing precision/recall/ROC-AUC and the learned coefficients. Swapping in real chargeback-labeled data later is a change to this one file; nothing downstream changes.

## 6. Known limitations (found by the eval harness, not hidden)

Running `python -m scripts.evaluate --n 300` against a synthetic adversarial population currently reports (your exact numbers will vary run to run — the harness uses real randomness in the sizes/timings below, not a fixed seed for those):

- **100% catch rate on the "hard" fraud types**: tampered signatures, expired mandates, replayed mandates, and fraud-ring agent histories are all caught before approval, every run — these are hard cryptographic/temporal/reputation checks, so ~100% is expected by construction and the eval mainly confirms the wiring is correct.
- **A coordinated burst of individually-clean agents is now caught, but not immediately.** `scripts/evaluate.py` injects dedicated "incident" blocks — dozens of freshly-seeded, well-established-looking agent identities hitting the merchant from one platform within a few compressed minutes — the exact pattern the *per-agent* velocity cap structurally cannot see (see §8 below and `app/policy/engine.py`'s `platform_distinct_agents_cap_per_hour`). A typical run catches roughly 70% of a 40-agent incident: the first dozen-plus orders are indistinguishable from organic growth (that's inherent to any threshold-based rate detector — you cannot flag a pattern before enough of the pattern has happened), and the platform-burst policy check trips once the distinct-agent count for that platform+merchant exceeds the configured cap within the rolling hour, correctly routing the rest to step-up. This is reported honestly as its own `fraud_coordinated_burst` row in the eval output, not folded into the other fraud categories, specifically so this "burn-in cost" is visible rather than averaged away.
- **A genuine friction cost on legitimate new agents:** every `legit_new` case in the eval population is routed to step-up rather than approved outright, because the reputation model has no history to work with yet. In an *attended* deployment a merchant resolves this in seconds over WhatsApp; in the *unattended* eval harness (nobody answers) it defaults to reject. This is a real, measurable trade-off — safety over first-order convenience for brand-new agent identities — and it is one of the most important numbers to be upfront about in a pitch, not the one to bury.
- **A meaningful chunk of `legit_established` cases also get stepped up** — driven almost entirely by the reputation score dipping below the step-up threshold, not by the burst check (the eval harness attributes each step-up to its actual trigger reason so this isn't a guess). The synthetic `legit_established` population intentionally spans a wide range (as few as 20 prior orders with up to 2 disputes on file — a genuinely elevated ~10% dispute rate at that volume), so some of what's labeled "established" is, honestly, borderline. This became visible once `scripts/evaluate.py` was fixed to spread simulated order timestamps across a realistic multi-hour window (see §8) instead of compressing an entire eval run's history into the same couple of wall-clock seconds — that earlier timing artifact was itself inflating *every* reused agent's per-hour order velocity, which had been masking this reputation-driven friction behind a much larger, less honest, velocity-driven friction number. Fixing the artifact didn't remove the friction, it just correctly re-attributed it.

## 7. Tech stack and why

Python + FastAPI (fast to build, typed, matches the "AI Builder" audience), Pydantic for every data contract, `cryptography` for real Ed25519 (not a toy HMAC), scikit-learn for a small honest classifier, SQLite for both the reputation store and the audit log (zero ops overhead for a hackathon-scoped service, trivially swappable for Postgres later), PyYAML for merchant policy, and the official `anthropic` SDK as an optional rationale-writing layer — deliberately mirroring that Razorpay's own Agent Studio is built on Anthropic's Claude Agent SDK.

## 8. What a production version adds next

Live trust-root discovery per protocol spec instead of a seeded registry; a real WhatsApp Business API integration for escalation; a reputation model retrained on real dispute/chargeback outcomes via the `/outcomes` feedback endpoint (already wired, just not yet fed by anything real); per-merchant policy configs behind an actual multi-tenant API instead of one YAML file; and the fourth protocol adapter (Visa TAP / Mastercard Agent Pay) as those specs stabilize.

**On the platform-burst signal specifically** (`app/reputation/store.get_platform_burst`, `app/policy/engine.py`'s `platform_distinct_agents_cap_per_hour`): today it's a single `COUNT(DISTINCT agent_id)` SQL query over a rolling window at decision time, which is real and correct but a blunt instrument — a fixed cap can't tell a genuinely growing merchant's organic traffic apart from a slow-ramping ring except by the number itself. Production hardening would mean (1) a per-merchant, learned or at least seasonally-adjusted cap instead of one static number in YAML, (2) a shorter, sliding sub-window (e.g. distinct agents per 5 minutes, not per hour) so a *fast* burst is caught well before it reaches the current hourly threshold, and (3) treating this the same way `/outcomes` treats reputation — feeding confirmed-ring outcomes back in as labels rather than only ever hand-tuning the cap. It's also worth being explicit that this only catches disposable-identity rings that spread across *distinct agent IDs*; a ring using one long-lived, otherwise-clean agent identity still has to be caught by the existing per-agent velocity cap and reputation model, not this one.
