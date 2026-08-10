"""The ledger on its own, without a policy engine in the way.

This is the half of the temporal rule that Cedar cannot hold, so it is also the
half that no policy file constrains. A wrong answer here reaches the engine
looking exactly like a right one, which is why these boundaries are tested from
both sides rather than through a verdict.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone

import pytest

from temporal_policy.cedar.v2.ledger import WINDOW, Ledger
from temporal_policy.money import cents
from temporal_policy.spec import BASE, ORDER

OTHER_ORDER = "ORD-2"


def test_an_empty_ledger_reports_the_window_it_was_asked_about() -> None:
    """The span is part of the answer, because the policy checks it."""
    window = Ledger().window(ORDER, BASE)

    assert window.order_id == ORDER
    assert window.total_cents == 0
    assert window.end - window.start == WINDOW


def test_payments_on_another_order_are_not_counted() -> None:
    """Each order has its own budget, and only this filter enforces it."""
    ledger = Ledger()
    ledger.record(OTHER_ORDER, cents(7_000), BASE)

    assert ledger.window(ORDER, BASE).total_cents == 0
    assert ledger.window(OTHER_ORDER, BASE).total_cents == 7_000


@pytest.mark.parametrize(
    ("age", "counted"),
    [
        (timedelta(0), True),
        (WINDOW - timedelta(seconds=1), True),
        (WINDOW, True),
        (WINDOW + timedelta(seconds=1), False),
    ],
    ids=["now", "just-inside", "exactly-a-window-ago", "just-outside"],
)
def test_the_window_is_closed_at_its_older_end(age: timedelta, counted: bool) -> None:
    """Spec case T6b pins the boundary; these pin the second either side of it.

    A payment made exactly a window ago still counts. Tested from both sides
    because an exclusive comparison passes every case that is merely near the
    edge and fails only on the edge itself.
    """
    ledger = Ledger()
    ledger.record(ORDER, cents(7_000), BASE - age)

    assert (ledger.window(ORDER, BASE).total_cents == 7_000) is counted


def test_a_payment_recorded_after_the_instant_asked_about_is_not_counted() -> None:
    """The younger end of the window, which no spec case reaches.

    Every case in the table moves forward in time, so a total that ignored this
    bound would pass all of them and still be wrong for any caller asking what
    an order had paid by some earlier instant.
    """
    ledger = Ledger()
    ledger.record(ORDER, cents(7_000), BASE + timedelta(seconds=1))

    assert ledger.window(ORDER, BASE).total_cents == 0
    assert ledger.window(ORDER, BASE + timedelta(seconds=1)).total_cents == 7_000


def test_payments_inside_the_window_are_added_together() -> None:
    """Salami slicing, at the layer that detects it rather than the one that refuses."""
    ledger = Ledger()
    for after_minutes in (0, 1, 2):
        ledger.record(ORDER, cents(5_000), BASE + timedelta(minutes=after_minutes))

    assert ledger.window(ORDER, BASE + timedelta(minutes=2)).total_cents == 15_000


@pytest.mark.parametrize(
    "call",
    [
        lambda ledger, at: ledger.record(ORDER, cents(1), at),
        lambda ledger, at: ledger.window(ORDER, at),
    ],
    ids=["record", "window"],
)
def test_a_naive_instant_is_refused_at_both_doors(
    call: Callable[[Ledger, datetime], object],
) -> None:
    """A window measured from an instant with no timezone means nothing.

    Both entry points, because a ledger that normalised only on the way out
    would compare aware instants against whatever the recorder happened to mean.
    """
    with pytest.raises(ValueError, match="timezone-aware"):
        call(Ledger(), BASE.replace(tzinfo=None))


def test_an_instant_in_another_timezone_measures_the_same_window() -> None:
    """Normalised rather than refused: one moment written two ways is one moment.

    The payment below sits exactly on the older edge, so an offset that survived
    into the comparison would move it out of the window rather than merely
    reformat it.
    """
    ledger = Ledger()
    ledger.record(ORDER, cents(7_000), BASE)
    elsewhere = (BASE + WINDOW).astimezone(timezone(timedelta(hours=9)))

    assert ledger.window(ORDER, elsewhere).total_cents == 7_000


def test_sub_second_precision_is_dropped() -> None:
    """Dogwood's timestamps are whole seconds, so Cedar's window uses them too.

    Kept at full precision, the same pair of payments falls on opposite sides of
    the edge in the two engines and a comparison between them stops measuring
    the rule rather than the clock.
    """
    ledger = Ledger()
    ledger.record(ORDER, cents(6_000), BASE - WINDOW + timedelta(milliseconds=1))
    ledger.record(OTHER_ORDER, cents(6_000), BASE - WINDOW - timedelta(milliseconds=1))

    # Both floor to a whole second: the first onto the edge, the second past it.
    assert ledger.window(ORDER, BASE).total_cents == 6_000
    assert ledger.window(OTHER_ORDER, BASE).total_cents == 0
