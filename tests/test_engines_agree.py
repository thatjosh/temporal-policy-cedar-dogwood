"""The two engines, compared to each other rather than to the table.

Every other agreement claim in this repo is inferred: both suites are checked
against the same case table, so anything the table cannot express is invisible
to both. The table moves in whole minutes, which is why a change to either
engine's timestamp resolution went unnoticed until it was looked for.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from temporal_policy.cedar.v2 import build_gate as build_cedar
from temporal_policy.cedar.v2.ledger import Ledger as CedarLedger
from temporal_policy.decision import EngineUnavailableError
from temporal_policy.dogwood.v2 import build_gate as build_dogwood
from temporal_policy.dogwood.v2 import build_ledger as build_dogwood_ledger
from temporal_policy.money import Cents, cents
from temporal_policy.spec import BASE, ORDER, UNKNOWN_ORDER

Payments = list[tuple[int, Cents]]

# Offsets finer than the case table can express, in seconds rather than minutes.
SUB_MINUTE: list[tuple[str, Payments]] = [
    ("one second apart", [(0, cents(6_000)), (1, cents(6_000))]),
    ("a second inside the window", [(0, cents(6_000)), (3_599, cents(6_000))]),
    ("exactly a window apart", [(0, cents(6_000)), (3_600, cents(6_000))]),
    ("a second outside the window", [(0, cents(6_000)), (3_601, cents(6_000))]),
]


def _run(decide, record, payments: Payments) -> list[bool]:  # type: ignore[no-untyped-def]
    verdicts = []
    for after_seconds, amount in payments:
        at = BASE + timedelta(seconds=after_seconds)
        decision = decide(ORDER, amount, at)
        if decision.allowed:
            record(ORDER, amount, at)
        verdicts.append(decision.allowed)
    return verdicts


@pytest.mark.parametrize(
    ("description", "payments"), SUB_MINUTE, ids=[name for name, _ in SUB_MINUTE]
)
def test_the_engines_agree_below_the_tables_resolution(
    description: str, payments: Payments, dogwood_binary: Path, tmp_path: Path
) -> None:
    """A window edge either engine rounds differently would show up here.

    Both are asked the same sequence directly, so nothing is mediated by the
    expectations in the table.
    """
    cedar_ledger = CedarLedger()
    cedar = _run(build_cedar(cedar_ledger).decide, cedar_ledger.record, payments)

    dogwood_ledger = build_dogwood_ledger(tmp_path / "ledger.trace")
    dogwood = _run(
        build_dogwood(dogwood_binary, dogwood_ledger).decide, dogwood_ledger.record, payments
    )

    assert cedar == dogwood, description


def test_both_engines_know_the_same_orders(dogwood_binary: Path, tmp_path: Path) -> None:
    """The two worlds are separate files and nothing else compares them.

    An order one engine has heard of and the other has not is allowed by one and
    denied by the other, which no case in the table can see: it uses one known
    order and one unknown one.
    """
    other_order = "ORD-2"
    cedar = build_cedar(CedarLedger())
    dogwood = build_dogwood(dogwood_binary, build_dogwood_ledger(tmp_path / "ledger.trace"))

    for order in (ORDER, other_order, UNKNOWN_ORDER):
        assert cedar.decide(order, cents(5_000), BASE).allowed == (
            dogwood.decide(order, cents(5_000), BASE).allowed
        ), order


def test_two_payments_in_one_second_part_the_engines(
    dogwood_binary: Path, tmp_path: Path
) -> None:
    """The one place they answer differently, and it is the engine's doing.

    Dogwood's trace contract requires strictly increasing timestamps, which are
    whole seconds, so a second payment in the same second is outside what the
    engine promises and the harness refuses to ask. Cedar has no trace and no
    such constraint, so it answers. Neither approves anything it should not.
    """
    at = BASE
    amount = cents(4_000)

    cedar_ledger = CedarLedger()
    cedar = build_cedar(cedar_ledger)
    assert cedar.decide(ORDER, amount, at).allowed
    cedar_ledger.record(ORDER, amount, at)
    assert cedar.decide(ORDER, amount, at).allowed, "still inside the cap"

    dogwood_ledger = build_dogwood_ledger(tmp_path / "ledger.trace")
    dogwood = build_dogwood(dogwood_binary, dogwood_ledger)
    assert dogwood.decide(ORDER, amount, at).allowed
    dogwood_ledger.record(ORDER, amount, at)
    with pytest.raises(EngineUnavailableError, match="do not move forward"):
        dogwood.decide(ORDER, amount, at)
