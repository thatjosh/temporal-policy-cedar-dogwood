"""Dogwood v1 against the shared case table, read down the v1 column.

The same table Cedar is judged by, and the same expected verdicts. Where the
two engines agree, the table is doing its job. Where they would disagree, the
table is what makes that visible instead of arguable.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from temporal_policy.dogwood.v1 import build_gate
from temporal_policy.money import cents
from temporal_policy.spec import BASE, CASES, ORDER, Case


@pytest.mark.parametrize("case", CASES, ids=lambda case: f"{case.id}-{case.pins_down}")
def test_spec_case(case: Case, dogwood_binary: Path) -> None:
    gate = build_gate(dogwood_binary)

    verdicts = [
        gate.decide(ORDER, payment.amount, payment.at).allowed for payment in case.payments
    ]

    assert verdicts == list(case.v1)


def test_a_denial_explains_itself_in_words(dogwood_binary: Path) -> None:
    """A refusal reads as prose, not as the rule's identifier.

    The same assertion the Cedar suite makes, and it holds only because the two
    policies are written in the same shape. Folding both limits into a single
    permit would make every refusal an implicit deny that names no rule, which
    would look like an engine limitation and would not be one.
    """
    over_the_cap = build_gate(dogwood_binary).decide(ORDER, cents(15_000), BASE)

    assert not over_the_cap.allowed
    assert "$100.00" in over_the_cap.reason
    assert "per-payment-cap" not in over_the_cap.reason
