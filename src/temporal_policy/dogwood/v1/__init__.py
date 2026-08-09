"""Dogwood v1: a cap on any single payment. No temporal rule.

The rule set is entirely in `pay.dw`. What lives here is the wiring: where the
policy files are, and the rules the file declares with the English for each.

The tuple is in file order and must stay that way, because a Dogwood verdict
names its rule by position where a Cedar one names it outright. That asymmetry
is a property of the engines. The gate checks this tuple against the policy at
construction, so a rule inserted, removed or reordered in one place and not the
other is a startup error rather than a neighbour's explanation shown to whoever
was refused.
"""

from pathlib import Path

from temporal_policy.dogwood.gate import DogwoodGate
from temporal_policy.guardrail import Guardrail

POLICY_DIR = Path(__file__).parent

# The permit's explanation is never shown, in either engine: a permit that fails
# to match yields an implicit deny naming no rule, and the gate falls back to
# "no policy permits...". Declared because every rule needs one.
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
)


def build_gate(binary: Path) -> DogwoodGate:
    return DogwoodGate(binary, POLICY_DIR, GUARDRAILS)
