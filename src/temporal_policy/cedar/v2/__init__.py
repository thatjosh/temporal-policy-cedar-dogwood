"""Cedar v2: v1's per-payment cap, plus a cap on the rolling 60-minute total.

Compare this module with its v1 counterpart to see what the temporal rule cost
Cedar. There is a new file, `ledger.py`, holding the half of the rule the engine
cannot express; two new rules in `policy.cedar` to judge what it reports; and
`build_gate` now takes an argument, because a gate without a ledger would answer
the temporal question from no evidence at all.
"""

from pathlib import Path

from temporal_policy.cedar.gate import CedarGate, WindowSource
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
    Guardrail(
        id="rolling-window-must-be-known",
        explanation=(
            "what this order has already paid in the last 60 minutes could not be established"
        ),
    ),
    Guardrail(
        id="rolling-window-cap",
        explanation="payments on one order may not exceed $100.00 in any 60 minutes",
    ),
)


def build_gate(ledger: WindowSource) -> CedarGate:
    """The ledger is supplied rather than owned: it stands in for a payment log.

    A caller that passes a fresh one for every decision gets a gate that always
    sees an empty window, which is v1 wearing v2's policy file.
    """
    return CedarGate(POLICY_DIR, GUARDRAILS, windows=ledger)
