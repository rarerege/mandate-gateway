# Execution Plan — Mandate Gateway

Target submission: a public repo + 5-minute pitch video + this architecture doc, before the **5 September 2026** application deadline. Work backward from a rehearsed demo, not forward from a feature list — a hackathon is lost more often to an unrehearsed final 10 minutes than to missing features.

## Status: Phase 0 is done

The working vertical slice described below already exists in this repo and passes its own test suite. What's listed as "done" is genuinely done — verified by running it, not just written. What remains is hardening, polish, and the human parts (pitch, talking points) a codebase can't do for you.

- [x] Repo scaffolded: `app/` (protocols, verification, reputation, policy, reasoning, escalation, audit, decision), `scripts/`, `tests/`
- [x] Three protocol adapters (AP2, ACP, UPI-agentic) normalizing into one `NormalizedMandate`
- [x] Real Ed25519 mandate signing/verification with expiry + replay (nonce) checks
- [x] A trained `sklearn` reputation classifier with a held-out precision/recall/ROC-AUC report
- [x] A YAML-driven deterministic policy engine (category, amount cap, velocity, step-up threshold)
- [x] Decision reasoner with an explicit, defensible cold-start rule (low score ≠ automatic reject)
- [x] LLM-or-template rationale generation (works with or without `ANTHROPIC_API_KEY`)
- [x] Simulated WhatsApp-style escalation with a safe default (unanswered → reject)
- [x] Hash-chained, tamper-evident audit log with an integrity-check endpoint
- [x] FastAPI surface (`/orders/authorize`, `/audit/{id}`, `/audit-chain/verify`, `/outcomes`, `/policy`)
- [x] 19 passing unit/integration tests
- [x] `scripts/run_demo_scenarios.py` — the 4 demo cases, run end-to-end against the real pipeline
- [x] `scripts/evaluate.py` — a 300-case adversarial eval reporting false-approve rate, verifier accuracy, and latency
- [x] `ARCHITECTURE.md` written against what's actually built, including an honest limitations section

## Phase 1 — Harden (before you touch the pitch video)

- [ ] Read `ARCHITECTURE.md` §6 (Known limitations) out loud to yourself and make sure you can defend every number in it under questioning — this is what a panel interview will actually probe.
- [ ] Re-run `python -m scripts.evaluate --n 500` (larger sample) and eyeball whether the false-approve rate stays at 0% or whether a larger sample surfaces an edge case. If it does, that's a *better* story for the pitch than a suspiciously perfect 0% — document it in the README rather than tuning it away.
- [x] Add one more adversarial case type to `scripts/evaluate.py`: an agent that is individually clean but part of a *coordinated* burst (multiple distinct agent IDs from the same platform hitting the same merchant in a short window) — this was the one realistic fraud pattern the per-agent velocity cap couldn't catch. **Fixed, not just named as future work:** `app/policy/engine.py` now has a `platform_distinct_agents_cap_per_hour` check fed by `app/reputation/store.get_platform_burst()`, wired into `app/decision/pipeline.py` and `app/reasoning/reasoner.py`'s step-up condition, with dedicated unit tests (`tests/test_policy.py`, `tests/test_pipeline.py`) and a dedicated `fraud_coordinated_burst` case type in `scripts/evaluate.py` (see `--burst-incidents`/`--burst-size`). Catches roughly 70% of a simulated ring in a typical run — see `ARCHITECTURE.md` §6 for the honest, unrounded story (why it's not 100%, and why that's inherent to any threshold-based detector, not a bug).
- [ ] Double-check `.gitignore` — confirm `data/reputation_model.joblib` and `data/demo_keys.json` are committed (so a fresh clone runs immediately) and `data/*.db` is not.
- [ ] Squash any WIP commits into a clean, readable history. A judge skimming commit history is part of the evaluation (`ai-playbook`'s own culture: "belts are earned by shipping").

## Phase 2 — The pitch (this is not an afterthought)

- [ ] Write the exact 5-minute demo script using the 4 scenarios already built:
  1. (30s) The problem, in one sentence: "Every major payments network shipped a way for AI agents to *sign* an order this year. Nobody shipped the part where the merchant decides whether to *trust* it."
  2. (60s) Scenario 1 live: trusted agent, ordinary order → instant, explainable approve.
  3. (90s) Scenario 2 live: new agent, high-value order → step-up → simulated WhatsApp approval → approved, with the rationale explicitly separating "why we paused" from "why we then said yes."
  4. (60s) Scenario 3 + 4 live: a policy-violating order and a tampered signature, both rejected — show the audit log entry and the hash-chain integrity check for one of them.
  5. (60s) The eval harness: run `scripts.evaluate` live (or show a captured run) and state the numbers plainly, including the friction-on-new-agents limitation — a builder who volunteers their system's weak point reads as more credible, not less.
- [ ] Record the video only after two full dry runs against the actual running server, not the plan — timing always slips in a live demo.
- [ ] Prepare one slide (or a spoken line) on "why this isn't an LLM wrapper": the verifier, policy engine, and decision boundary run with zero LLM calls; the LLM's job is exactly one thing — writing the rationale sentence — and the system runs correctly with `ANTHROPIC_API_KEY` unset.

## Phase 3 — Submission & interview prep

- [ ] Public repo: confirm `README.md` has a true 5-minute quickstart (clone → venv → install → train → seed → demo) that works on a machine that has never seen this code.
- [ ] Submit repo + video + `ARCHITECTURE.md` before 5 September 2026.
- [ ] Prepare answers to the questions a panel is likely to ask, using the material already in this repo:
  - *"Why isn't the decision boundary an LLM?"* → `app/reasoning/reasoner.py` module docstring, verbatim.
  - *"What happens if the reputation model is wrong?"* → the cold-start design decision + the step-up/escalation path as the safety net.
  - *"How do you know the audit log wasn't edited?"* → `verify_chain_integrity()`, live, in the interview if asked.
  - *"What would you build next?"* → `ARCHITECTURE.md` §8, including the production-hardening path for the platform-burst signal specifically (learned/seasonal caps, a shorter sliding sub-window, feeding confirmed rings back in as labels).
  - *"Why doesn't the coordinated-burst fix catch 100% of the simulated ring?"* → `ARCHITECTURE.md` §6 — a threshold-based detector inherently can't flag a pattern before enough of the pattern has happened; naming that honestly is the point, not a gap to explain away.

## If you have extra time before the deadline

Priority order, most to least valuable given what's already built:
1. ~~The coordinated-burst detection gap~~ — done (see Phase 1 above and `ARCHITECTURE.md` §6/§8).
2. A second merchant policy profile (e.g. a subscriptions-only merchant) to show the policy engine isn't hard-coded to one demo config.
3. A minimal read-only dashboard (even a single HTML page hitting `/audit/{id}` and `/audit-chain/verify`) — only worth it if the core above is already solid, since a dashboard without the reasoning behind it is exactly the "AI wrapper" pattern this project is trying not to be.
