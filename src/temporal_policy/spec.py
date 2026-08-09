"""The case table both engines are judged by.

This lives in the package rather than in the test tree on purpose. The
experiment is "one rule, two engines, the same cases", so the cases are part of
what this repo asserts, not a private detail of one test file. Both engines will
import this table, which is what makes their results comparable: neither can
quietly be tested against a friendlier set of inputs.

Both the v1 and v2 columns are here even while only v1 is implemented. The table
is one artifact and splitting it in half would invite the two halves to drift.
The v2 column is the specification of what the temporal rule must do.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from temporal_policy.money import Cents, cents

# Every offset in the table is measured from here. A fixed instant rather than
# "now", so a case means the same thing on every machine and in every year.
BASE = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)

# `ORDER` must exist in each engine's world, and `UNKNOWN_ORDER` must not: the
# default denial for an unknown resource is a rule under test, not a detail.
ORDER = "ORD-1"
UNKNOWN_ORDER = "ORD-999"

ALLOW = True
DENY = False


@dataclass(frozen=True)
class Payment:
    """One proposed payment: when it is attempted, and for how much."""

    after_minutes: int
    amount: Cents

    @property
    def at(self) -> datetime:
        return BASE + timedelta(minutes=self.after_minutes)


@dataclass(frozen=True)
class Case:
    """A sequence of payments, and the verdict each must receive in each version.

    Each case starts from a fresh world, and its payments are decided in order.
    An allowed payment has executed and a denied one never happened, so only
    allowed ones may count towards a later verdict. v1 has no memory, so nothing
    yet carries an executed payment forward; the v2 harness must.
    """

    id: str
    payments: tuple[Payment, ...]
    v1: tuple[bool, ...]
    v2: tuple[bool, ...]
    pins_down: str

    def __post_init__(self) -> None:
        # A verdict column that does not line up with the payments is a typo
        # that would otherwise show up as a confusing test failure in one engine
        # and be blamed on the engine.
        if not len(self.payments) == len(self.v1) == len(self.v2):
            message = (
                f"{self.id}: {len(self.payments)} payments but "
                f"{len(self.v1)} v1 verdicts and {len(self.v2)} v2 verdicts"
            )
            raise ValueError(message)


CASES: tuple[Case, ...] = (
    Case(
        id="T1",
        payments=(Payment(0, cents(5_000)),),
        v1=(ALLOW,),
        v2=(ALLOW,),
        pins_down="trivial happy path",
    ),
    Case(
        id="T2",
        payments=(Payment(0, cents(15_000)),),
        v1=(DENY,),
        v2=(DENY,),
        pins_down="the per-payment cap, in both versions",
    ),
    Case(
        id="T3",
        payments=(Payment(0, cents(10_000)),),
        v1=(ALLOW,),
        v2=(ALLOW,),
        pins_down="the cap is inclusive: exactly $100.00 is allowed",
    ),
    Case(
        id="T3b",
        payments=(Payment(0, cents(10_001)),),
        v1=(DENY,),
        v2=(DENY,),
        pins_down="one cent over the cap is refused, which is the half T3 cannot see",
    ),
    Case(
        id="T4",
        payments=(Payment(0, cents(6_000)), Payment(5, cents(6_000))),
        v1=(ALLOW, ALLOW),
        v2=(ALLOW, DENY),
        pins_down="the whole point of the temporal rule",
    ),
    Case(
        id="T5",
        payments=(Payment(0, cents(6_000)), Payment(90, cents(6_000))),
        v1=(ALLOW, ALLOW),
        v2=(ALLOW, ALLOW),
        pins_down="outside the window, so no false positive",
    ),
    Case(
        id="T6",
        payments=(Payment(0, cents(6_000)), Payment(59, cents(6_000))),
        v1=(ALLOW, ALLOW),
        v2=(ALLOW, DENY),
        pins_down="just inside the window",
    ),
    Case(
        id="T6b",
        payments=(Payment(0, cents(6_000)), Payment(60, cents(6_000))),
        v1=(ALLOW, ALLOW),
        v2=(ALLOW, DENY),
        pins_down="exactly 60 minutes, the boundary T6 and T7 straddle without naming",
    ),
    Case(
        id="T7",
        payments=(Payment(0, cents(6_000)), Payment(61, cents(6_000))),
        v1=(ALLOW, ALLOW),
        v2=(ALLOW, ALLOW),
        pins_down="just outside the window",
    ),
    Case(
        id="T8",
        payments=(
            Payment(0, cents(5_000)),
            Payment(1, cents(5_000)),
            Payment(2, cents(5_000)),
        ),
        v1=(ALLOW, ALLOW, ALLOW),
        v2=(ALLOW, ALLOW, DENY),
        pins_down="salami slice: each payment legal, the sum is not",
    ),
    Case(
        id="T9",
        payments=(Payment(0, cents(0)),),
        v1=(DENY,),
        v2=(DENY,),
        pins_down="zero is not a payment",
    ),
    Case(
        id="T10",
        payments=(Payment(0, cents(-5_000)),),
        v1=(DENY,),
        v2=(DENY,),
        pins_down="a negative payment is a charge against the customer",
    ),
)
