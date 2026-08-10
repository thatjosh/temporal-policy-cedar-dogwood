"""Dogwood v2: v1's per-payment cap, plus a cap on the rolling hour.

The rule set is still entirely in `pay.dw`, and the rolling total is summed by
the engine out of the event log. Nothing in Python adds a payment up, which is
the claim this half of the repo exists to test.

What the temporal rule cost is agreement between files: three must name the
same field, and `pay.dw` says what happens when they do not. The fourth
agreement, between the rules in `pay.dw` and the tuple below, is the one the
engine helps with, emitting the ids for the gate to compare.
"""

from pathlib import Path

from temporal_policy.dogwood.gate import DogwoodGate, read_world
from temporal_policy.dogwood.ledger import Ledger
from temporal_policy.guardrail import Guardrail

POLICY_DIR = Path(__file__).parent
EVENT_SCHEMA = POLICY_DIR / "event.dwschema"

# In file order: a Dogwood verdict names its rule by position, and the gate
# refuses to serve if this tuple and the policy have drifted apart.
GUARDRAILS = (
    Guardrail(
        id="agent-may-pay",
        explanation="this agent may not pay against this order",
    ),
    Guardrail(
        id="amount-must-be-positive",
        explanation="the amount must be a positive number of cents",
    ),
    Guardrail(
        id="per-payment-cap",
        explanation="a single payment may not exceed $100.00",
    ),
    Guardrail(
        id="rolling-hour-cap",
        explanation="payments on this order may not total more than $100.00 in any 60 minutes",
    ),
)


def build_ledger(path: Path) -> Ledger:
    return Ledger(path, read_world(POLICY_DIR))


def build_gate(binary: Path, ledger: Ledger) -> DogwoodGate:
    return DogwoodGate(binary, POLICY_DIR, GUARDRAILS, ledger, EVENT_SCHEMA)
