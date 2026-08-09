"""Cedar v1: a cap on any single payment. No temporal rule.

The rule set is entirely in `policy.cedar`. What lives here is the wiring: where
the policy files are, and the English for each rule that can refuse. Compare
this module with its v2 counterpart to see what the temporal rule cost Cedar.
"""

from pathlib import Path

from temporal_policy.cedar.gate import CedarGate
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


def build_gate() -> CedarGate:
    return CedarGate(POLICY_DIR, GUARDRAILS)
