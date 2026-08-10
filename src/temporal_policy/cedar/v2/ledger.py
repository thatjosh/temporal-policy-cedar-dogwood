"""The half of the temporal rule that Cedar cannot hold.

Cedar decides from the request, the policies and the entity store. History is
none of those, so the rolling total is summed here and handed over as a fact,
and from then on the guardrail holds only while this file and `policy.cedar`
agree. Nothing but the tests checks that they do.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from temporal_policy.cedar.gate import Window
from temporal_policy.clock import require_utc
from temporal_policy.money import Cents, cents

# The other copy of this number is `duration("60m")` in policy.cedar. This one
# decides which payments are summed, that one decides whether to trust the
# answer, and a change to either alone is a silent disagreement.
WINDOW = timedelta(minutes=60)


@dataclass(frozen=True)
class _Executed:
    order_id: str
    amount: Cents
    at: datetime


class Ledger:
    """Executed payments, in memory, standing in for a real payment log."""

    def __init__(self) -> None:
        self._executed: list[_Executed] = []

    def record(self, order_id: str, amount: Cents, at: datetime) -> None:
        """Remember a payment that executed. A refusal must not be recorded.

        Letting one consume the budget would turn a denial into a second,
        quieter denial of the next legitimate payment.
        """
        self._executed.append(_Executed(order_id, amount, _whole_seconds(at)))

    def window(self, order_id: str, at: datetime) -> Window:
        """What this order has already paid over the window ending at `at`.

        Closed at both ends: a payment made exactly a window ago still counts
        (spec case T6b), and one recorded later than `at` has not happened yet
        as far as this decision is concerned.
        """
        end = _whole_seconds(at)
        start = end - WINDOW
        total = sum(
            executed.amount
            for executed in self._executed
            if executed.order_id == order_id and start <= executed.at <= end
        )
        return Window(order_id=order_id, start=start, end=end, total_cents=cents(total))


def _whole_seconds(at: datetime) -> datetime:
    """Drop sub-second precision, because Dogwood's timestamps are integers.

    Without this the same pair of payments falls on opposite sides of the window
    edge in the two engines, and a comparison between them stops measuring the
    rule.
    """
    return require_utc(at).replace(microsecond=0)
