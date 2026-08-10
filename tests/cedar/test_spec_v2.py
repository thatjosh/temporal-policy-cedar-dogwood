"""Cedar v2 against the shared case table, read down the v2 column.

Same driver and same cases as v1, so the difference in the verdicts is the
temporal rule and nothing else. T4, T6, T6b and T8 are the ones that move: each
pays more than the cap in total while every single payment is inside it, and v1
allows all of them.

Below the table are the things the table cannot reach: T11, and the clauses that
only fire when the window handed to the policy is not the one the ledger built.

Cedar reports the rules behind a denial in an order that varies between runs, so
a refusal by two rules at once has no stable sentence order. Every assertion on
a reason here is on a fragment for that reason.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from temporal_policy.cedar.gate import (
    POLICY_FILE,
    SCHEMA_FILE,
    WORLD_FILE,
    CedarGate,
    LedgerUnavailableError,
    Window,
)
from temporal_policy.cedar.v2 import GUARDRAILS, POLICY_DIR, build_gate
from temporal_policy.cedar.v2.ledger import WINDOW, Ledger
from temporal_policy.decision import EngineUnavailableError
from temporal_policy.money import Cents, cents
from temporal_policy.spec import (
    ALLOW,
    BASE,
    CASES,
    DENY,
    ORDER,
    UNKNOWN_ORDER,
    Case,
    Payment,
    run_case,
)

OTHER_ORDER = "ORD-2"


class _Unavailable:
    """A ledger that cannot answer. Spec case T11."""

    def window(self, order_id: str, at: datetime) -> Window:
        message = "the payment log is unreachable"
        raise LedgerUnavailableError(message)


class _Doctored:
    """A ledger that answers, but not about the payment being judged."""

    def __init__(self, answer: Window) -> None:
        self._answer = answer

    def window(self, order_id: str, at: datetime) -> Window:
        return self._answer


def _gate_over(answer: Window | None = None) -> CedarGate:
    """A v2 gate whose history is a fixed answer, or no answer at all."""
    source = _Unavailable() if answer is None else _Doctored(answer)
    return CedarGate(POLICY_DIR, GUARDRAILS, windows=source)


def _paid(amount: Cents, at: datetime, order_id: str = ORDER) -> Ledger:
    """A ledger holding one payment that executed."""
    ledger = Ledger()
    ledger.record(order_id, amount, at)
    return ledger


@pytest.mark.parametrize("case", CASES, ids=lambda case: f"{case.id}-{case.pins_down}")
def test_spec_case(case: Case) -> None:
    ledger = Ledger()

    assert run_case(case, build_gate(ledger).decide, ledger.record) == list(case.v2)


def test_a_payment_that_was_denied_never_happened() -> None:
    """Only executed payments may consume the window's budget.

    Driven through the shared runner, which records a payment only when the gate
    allowed it. A gate that counted its own refusals would refuse the whole cap
    to the next legitimate payment, turning one denial into two.
    """
    refused_then_full = Case(
        id="denied-then-full",
        payments=(Payment(0, cents(15_000)), Payment(1, cents(10_000))),
        v1=(DENY, ALLOW),
        v2=(DENY, ALLOW),
        pins_down="a refusal leaves the window untouched",
    )
    ledger = Ledger()

    verdicts = run_case(refused_then_full, build_gate(ledger).decide, ledger.record)

    assert verdicts == [DENY, ALLOW]


def test_the_window_cap_is_inclusive() -> None:
    """$100.00 exactly, spread across two payments, is allowed."""
    gate = build_gate(_paid(cents(6_000), BASE))

    decision = gate.decide(ORDER, cents(4_000), BASE + timedelta(minutes=1))

    assert decision.allowed


def test_one_cent_over_the_window_cap_is_refused() -> None:
    """The half the inclusive case cannot see: a cap tested from one side is a range."""
    gate = build_gate(_paid(cents(6_000), BASE))

    decision = gate.decide(ORDER, cents(4_001), BASE + timedelta(minutes=1))

    assert not decision.allowed
    assert "in any 60 minutes" in decision.reason


def test_a_refusal_by_the_window_names_the_window_rather_than_the_payment() -> None:
    """The two caps are the same number, so only the sentence tells them apart.

    A payment of $60.00 is comfortably inside the per-payment cap. If this
    refusal read as "a single payment may not exceed $100.00" the customer would
    be told something demonstrably false about the payment in front of them.
    """
    gate = build_gate(_paid(cents(6_000), BASE))

    decision = gate.decide(ORDER, cents(6_000), BASE + timedelta(minutes=1))

    assert not decision.allowed
    assert "payments on one order may not exceed $100.00 in any 60 minutes" in decision.reason
    assert "a single payment" not in decision.reason


def test_the_per_payment_cap_still_refuses_in_its_own_words() -> None:
    """v2 subsumes v1's verdict, which leaves only the sentence to hold the rule.

    Against an empty window the rolling rule refuses everything over the cap by
    itself, so a per-payment cap that had drifted upwards would go on producing
    the right verdict and the wrong explanation. T3 pins the other side of this
    boundary, where a cap that had drifted downwards changes the verdict.
    """
    decision = build_gate(Ledger()).decide(ORDER, cents(10_001), BASE)

    assert not decision.allowed
    assert "a single payment may not exceed $100.00" in decision.reason


def test_a_window_read_without_its_guard_is_refused_at_construction(tmp_path: Path) -> None:
    """The validator, not the run time, is what keeps the `has` on `window`.

    An unguarded read of an attribute that turns out to be missing is skipped at
    run time, and a skipped forbid is an absent forbid. Because `window` is
    optional, Cedar refuses to validate the policy at all, so the guard the
    temporal rules rest on cannot be dropped by a later edit and go unnoticed.
    """
    for name in (POLICY_FILE, SCHEMA_FILE, WORLD_FILE):
        source = (POLICY_DIR / name).read_text(encoding="utf-8")
        (tmp_path / name).write_text(source, encoding="utf-8")
    policy = tmp_path / POLICY_FILE
    unguarded = policy.read_text(encoding="utf-8").replace("context has window &&\n  ", "")
    assert unguarded != policy.read_text(encoding="utf-8"), "the guard was not there to remove"
    policy.write_text(unguarded, encoding="utf-8")

    with pytest.raises(EngineUnavailableError, match="does not validate"):
        CedarGate(tmp_path, GUARDRAILS)


def test_another_order_spends_its_own_budget() -> None:
    """The window is per order, and the ledger is what makes that true.

    Nothing in the policy can see this: it is handed a total and told which
    order it was measured over, so an unfiltered sum would arrive looking
    exactly like a correct one.
    """
    gate = build_gate(_paid(cents(10_000), BASE, order_id=OTHER_ORDER))

    decision = gate.decide(ORDER, cents(10_000), BASE)

    assert decision.allowed


def test_a_ledger_that_cannot_answer_denies_the_payment() -> None:
    """Spec case T11, and the whole reason `window` is optional in the schema.

    The gate sends no window rather than a guessed one, and the policy's `has`
    guard turns the absence into a refusal. A zero would have been an approval.
    A required attribute would have made the request malformed, which denies
    too, but says the engine broke rather than that a rule did its job.
    """
    decision = _gate_over().decide(ORDER, cents(5_000), BASE)

    assert not decision.allowed
    assert "could not be established" in decision.reason
    assert "could not apply every rule" not in decision.reason


def test_a_window_measured_over_another_order_is_refused() -> None:
    """The policy checks the answer is about the payment being judged.

    It cannot check the total, but it can check what the total is a total of,
    and this is the only clause that does.
    """
    elsewhere = Window(OTHER_ORDER, BASE - WINDOW, BASE, cents(0))

    decision = _gate_over(elsewhere).decide(ORDER, cents(5_000), BASE)

    assert not decision.allowed
    assert "could not be established" in decision.reason


def test_the_policy_and_the_ledger_must_agree_on_the_window_length() -> None:
    """The seam. `WINDOW` decides what is summed; the policy decides what it trusts.

    Two files hold the same number and nothing but this reconciles them, which
    is what the temporal rule cost Cedar. A window longer than the one the
    policy names would buy extra budget, so refusing is the only safe default.
    """
    stretched = Window(ORDER, BASE - WINDOW - timedelta(minutes=1), BASE, cents(0))

    decision = _gate_over(stretched).decide(ORDER, cents(5_000), BASE)

    assert not decision.allowed
    assert "could not be established" in decision.reason


def test_an_amount_large_enough_to_overflow_is_refused_by_a_rule() -> None:
    """Why the window cap is stated as a remaining budget instead of as a sum.

    Cedar's Long is a signed 64-bit integer and its addition overflows. An
    overflowing forbid errors, a policy that errors is skipped, and that is how
    an arithmetic detail becomes a missing guardrail. Subtracting from the cap
    keeps the agent's number out of the arithmetic, so this refusal comes from
    the rules rather than from the gate's error handling.
    """
    gate = build_gate(_paid(cents(5_000), BASE))

    decision = gate.decide(ORDER, cents(2**63 - 1), BASE + timedelta(minutes=1))

    assert not decision.allowed
    assert "$100.00" in decision.reason
    assert "could not apply every rule" not in decision.reason


def test_an_impossible_running_total_cannot_become_an_approval() -> None:
    """The other operand, which is ours rather than the agent's.

    A total no ledger should ever produce still overflows the subtraction. The
    gate reports errors before it reports a verdict, so the skipped forbid does
    not become an allow, and this is the test that holds that ordering in place.
    """
    corrupt = Window(ORDER, BASE - WINDOW, BASE, cents(-(2**63)))

    decision = _gate_over(corrupt).decide(ORDER, cents(1), BASE)

    assert not decision.allowed


def test_the_window_boundary_is_measured_in_whole_seconds() -> None:
    """The ledger floors instants, so a second is the finest the boundary sees.

    A payment exactly a window old still counts; one a second older does not.
    Sub-second offsets move nothing, which is what keeps this engine's answer
    the same as the one that can only speak in whole seconds.
    """
    gate = build_gate(_paid(cents(6_000), BASE))

    on_the_boundary = gate.decide(ORDER, cents(6_000), BASE + WINDOW)
    a_moment_later = gate.decide(ORDER, cents(6_000), BASE + WINDOW + timedelta(milliseconds=1))
    a_second_later = gate.decide(ORDER, cents(6_000), BASE + WINDOW + timedelta(seconds=1))

    assert not on_the_boundary.allowed
    assert not a_moment_later.allowed, "a millisecond is below the resolution of the window"
    assert a_second_later.allowed


def test_an_order_belonging_to_nobody_is_still_denied() -> None:
    """v1's default denial, unchanged by the temporal rule.

    Worth re-asserting rather than assuming: both new rules quote `resource`,
    and one that quoted it wrongly could have started permitting orders the
    entity store has never heard of.
    """
    decision = build_gate(Ledger()).decide(UNKNOWN_ORDER, cents(5_000), BASE)

    assert not decision.allowed
    assert "no policy permits" in decision.reason


def test_an_allowed_payment_names_the_rule_that_permitted_it() -> None:
    """Identical to v1's sentence, because two new forbids must not read as one."""
    allowed = build_gate(Ledger()).decide(ORDER, cents(5_000), BASE)

    assert allowed.allowed
    assert allowed.reason == "allowed by agent-may-pay: no guardrail objected"
