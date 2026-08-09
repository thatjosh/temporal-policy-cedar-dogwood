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
from temporal_policy.spec import BASE, CASES, ORDER, Case, Payment, run_case


@pytest.mark.parametrize("case", CASES, ids=lambda case: f"{case.id}-{case.pins_down}")
def test_spec_case(case: Case) -> None:
    gate = build_gate()

    assert run_case(case, gate.decide) == list(case.v1)


def test_a_denial_explains_itself_in_words() -> None:
    """A refusal reads as prose, not as the rule's identifier.

    The identifier is what a caller sees when a guardrail was added without an
    explanation, so this is the check that the pairing actually reached a human.
    """
    over_the_cap = build_gate().decide(ORDER, cents(15_000), BASE)

    assert not over_the_cap.allowed
    assert "$100.00" in over_the_cap.reason
    assert "per-payment-cap" not in over_the_cap.reason


def test_an_allowed_payment_names_the_rule_that_permitted_it() -> None:
    """The counterpart of the Dogwood assertion, word for word.

    The two engines are only comparable if identical decisions read identically,
    and that holds because the rule ids are spelled the same in both policies.
    Nothing else enforces it.
    """
    allowed = build_gate().decide(ORDER, cents(5_000), BASE)

    assert allowed.allowed
    assert allowed.reason == "allowed by agent-may-pay: no guardrail objected"


@pytest.mark.parametrize(
    ("first", "second"),
    [(10, 5), (5, 5)],
    ids=["backwards", "same-instant"],
)
def test_a_case_whose_payments_do_not_move_forward_is_refused(first: int, second: int) -> None:
    """Dogwood's trace contract requires strictly increasing timestamps.

    The engine does not enforce it: a backdated event replays without complaint.
    v2 sums a window, so a case that walked backwards would be measuring
    something neither engine promises to get right.
    """
    with pytest.raises(ValueError, match="must move forward in time"):
        Case(
            id="backwards",
            payments=(Payment(first, cents(1)), Payment(second, cents(1))),
            v1=(True, True),
            v2=(True, True),
            pins_down="a case that should not be constructible",
        )


@pytest.mark.parametrize(
    ("v1", "v2"),
    [((True,), (True, True)), ((True, True), (True,))],
    ids=["short-v1", "short-v2"],
)
def test_a_case_whose_verdict_column_is_the_wrong_length_is_refused(
    v1: tuple[bool, ...], v2: tuple[bool, ...]
) -> None:
    """The other half of the case table's own validation, both columns.

    A column that does not line up with the payments would otherwise surface as
    a confusing failure in one engine and be blamed on the engine. The v2 column
    matters as much as the v1 one: it is the specification the temporal rule
    will be judged against, and nothing else reads it yet.
    """
    with pytest.raises(ValueError, match="verdicts"):
        Case(
            id="short-column",
            payments=(Payment(0, cents(1)), Payment(5, cents(1))),
            v1=v1,
            v2=v2,
            pins_down="a case that should not be constructible",
        )
