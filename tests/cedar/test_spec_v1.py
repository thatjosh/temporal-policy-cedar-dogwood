"""Cedar v1 against the shared case table, read down the v1 column.

v1 has no memory, so the interesting cases are the ones it is *expected* to let
through: T4, T6 and T8 each pay more than the cap in total and are allowed,
because every individual payment is inside it. Those are not failures here. They
are the measurement of what a non-temporal rule cannot do, and v2 is what
changes them.
"""

from __future__ import annotations

import pytest

from temporal_policy.cedar.v1 import build_gate
from temporal_policy.money import cents
from temporal_policy.spec import BASE, CASES, ORDER, Case


@pytest.mark.parametrize("case", CASES, ids=lambda case: f"{case.id}-{case.pins_down}")
def test_spec_case(case: Case) -> None:
    gate = build_gate()

    verdicts = [
        gate.decide(ORDER, payment.amount, payment.at).allowed for payment in case.payments
    ]

    assert verdicts == list(case.v1)


def test_a_denial_explains_itself_in_words() -> None:
    """A refusal reads as prose, not as the rule's identifier.

    The identifier is what a caller sees when a guardrail was added without an
    explanation, so this is the check that the pairing actually reached a human.
    """
    over_the_cap = build_gate().decide(ORDER, cents(15_000), BASE)

    assert not over_the_cap.allowed
    assert "$100.00" in over_the_cap.reason
    assert "per-payment-cap" not in over_the_cap.reason
