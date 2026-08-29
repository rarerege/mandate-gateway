"""Simulated human escalation channel.

Razorpay's own published Agent Studio principles say sensitive actions
"escalate to the merchant — typically on WhatsApp." This module stands in
for that channel: in the hackathon build it logs what *would* be sent and
returns a pre-scripted or interactively-supplied response, so the full
step-up path is exercised end-to-end without a real messaging integration.
Swapping in an actual WhatsApp Business API call is an isolated change to
`send_step_up_request` alone.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class StepUpRequest:
    merchant_id: str
    agent_id: str
    amount_minor_units: int
    category: str
    reason: str


@dataclass
class StepUpResponse:
    approved: bool
    responder: str
    note: str = ""


def send_step_up_request(
    request: StepUpRequest, auto_response: StepUpResponse | None = None, verbose: bool = True
) -> StepUpResponse:
    """In production this sends a WhatsApp message to the merchant and
    blocks (or webhooks back) until they tap Approve/Reject. For the demo,
    pass `auto_response` to script an outcome, or omit it to get a
    conservative default (reject-if-unattended) — a step-up that nobody
    ever answers must never silently become an approval. `verbose=False`
    (used by the batch evaluation harness) skips the printed transcript so
    a few hundred cases don't flood the terminal."""

    if verbose:
        print(
            f"[escalation] WhatsApp -> merchant {request.merchant_id}: "
            f"Agent '{request.agent_id}' wants to spend "
            f"{request.amount_minor_units/100:.2f} on '{request.category}'. "
            f"Reason for review: {request.reason}. Approve? [Y/N]"
        )
    if auto_response is not None:
        if verbose:
            print(f"[escalation] merchant responded: {'APPROVE' if auto_response.approved else 'REJECT'}")
        return auto_response

    return StepUpResponse(approved=False, responder="system-default", note="no response received; defaulted to reject")
