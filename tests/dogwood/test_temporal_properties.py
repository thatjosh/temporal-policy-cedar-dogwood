"""What the rolling-hour rule rests on, beyond the case table.

Each of these is a counter-example. Remove the thing it defends and the cap
either stops being the rule that was written or stops being applied at all, in
every case without an error, a warning or a non-zero exit.
"""

from __future__ import annotations

import json
import subprocess
from datetime import timedelta
from pathlib import Path

import pytest

from temporal_policy.decision import EngineUnavailableError
from temporal_policy.dogwood.cli import DogwoodCli
from temporal_policy.dogwood.gate import POLICY_FILE, SCHEMA_FILE, read_world
from temporal_policy.dogwood.ledger import LedgerUnobtainableError
from temporal_policy.dogwood.trace import AGENT, payment_event
from temporal_policy.dogwood.v2 import EVENT_SCHEMA, POLICY_DIR, build_gate, build_ledger
from temporal_policy.money import Cents, cents
from temporal_policy.spec import BASE, ORDER

# Declared in v2's entity store beside ORDER, and paid against by nothing in the
# case table. It exists so the claim "per order" can be refuted.
OTHER_ORDER = "ORD-2"

HALF_THE_CAP = cents(6_000)


def _cli(binary: Path, *, own_event_schema: bool) -> DogwoodCli:
    schemas: tuple[str, ...] = ("--policy-schema", str(POLICY_DIR / SCHEMA_FILE))
    if own_event_schema:
        schemas = (*schemas, "--event-schema", str(EVENT_SCHEMA))
    return DogwoodCli(binary=binary, policy=POLICY_DIR / POLICY_FILE, schemas=schemas)


def _event_without_the_order(amount: Cents, minutes: int) -> str:
    """A payment whose logged record names no order.

    Written out rather than produced by `payment_event`, because the point is
    the one field `payment_event` adds.
    """
    at = int((BASE + timedelta(minutes=minutes)).timestamp())
    payload = f"input: {{ amount_cents: {amount} }}"
    return (
        f'@{at} scope(principal: {AGENT}, resource: Support::Order::"{ORDER}") '
        f"{read_world(POLICY_DIR)} request_context({payload}) "
        f'Support::Action::"Pay"::request({payload})'
    )


def test_a_refused_payment_leaves_the_hour_untouched(
    dogwood_binary: Path, tmp_path: Path
) -> None:
    """A denied payment never happened, so it cannot spend the budget.

    The engine cannot enforce this: a trace event carries no verdict, so the sum
    would count an attempt exactly as it counts a transfer. It holds only
    because nothing writes a refusal to the ledger, and no case in the table
    proposes a payment that is refused and then asks what it cost.
    """
    ledger = build_ledger(tmp_path / "payments.log")
    gate = build_gate(dogwood_binary, ledger)

    refused = gate.decide(ORDER, cents(15_000), BASE)
    after = gate.decide(ORDER, cents(10_000), BASE + timedelta(minutes=1))

    assert not refused.allowed
    assert after.allowed, "the whole cap was still available"


@pytest.mark.parametrize(
    ("paid_against", "expected", "why"),
    [
        (OTHER_ORDER, True, "another order has its own budget"),
        (ORDER, False, "the control: the same order shares one"),
    ],
    ids=["other-order", "same-order"],
)
def test_the_hour_is_counted_per_order(
    paid_against: str,
    expected: bool,
    why: str,
    dogwood_binary: Path,
    tmp_path: Path,
) -> None:
    """`callerResource: resource` is the whole of what scopes the window.

    Without it every order draws on one budget, and the pair of cases is what
    makes that visible: the two differ only in which order was paid first.
    """
    ledger = build_ledger(tmp_path / "payments.log")
    gate = build_gate(dogwood_binary, ledger)
    ledger.record(paid_against, HALF_THE_CAP, BASE)

    decision = gate.decide(ORDER, HALF_THE_CAP, BASE + timedelta(minutes=5))

    assert decision.allowed is expected, why
    if not expected:
        assert "60 minutes" in decision.reason


def test_the_cap_permits_everything_when_an_event_omits_the_order(
    dogwood_binary: Path,
) -> None:
    """A predicate matches only events carrying every field it names.

    A non-match is silent, so the sum reads zero and the rule permits. This is
    the failure mode of dropping one field from a trace line, proven against the
    engine rather than asserted about it, with the same payments through the
    real renderer as the control.
    """
    cli = _cli(dogwood_binary, own_event_schema=True)
    world = read_world(POLICY_DIR)
    later = BASE + timedelta(minutes=5)

    without = cli.replay(
        (_event_without_the_order(HALF_THE_CAP, 0), _event_without_the_order(HALF_THE_CAP, 5))
    )
    with_it = cli.replay(
        (
            payment_event(ORDER, HALF_THE_CAP, BASE, world),
            payment_event(ORDER, HALF_THE_CAP, later, world),
        )
    )

    assert [verdict.allowed for verdict in without] == [True, True], "the cap vanished"
    assert [verdict.allowed for verdict in with_it] == [True, False]


def test_the_cap_permits_everything_under_the_default_event_schema(
    dogwood_binary: Path,
) -> None:
    """Why `event.dwschema` exists, measured rather than argued.

    The default schema pins `callerPrincipal` on every kind and appends that
    correlation to every predicate, whether or not the policy wrote it. These
    events carry no such field, so the predicate matches nothing. The policy is
    unchanged and still validates; only the schema is gone.
    """
    cli = _cli(dogwood_binary, own_event_schema=False)
    world = read_world(POLICY_DIR)
    later = BASE + timedelta(minutes=5)

    verdicts = cli.replay(
        (
            payment_event(ORDER, HALF_THE_CAP, BASE, world),
            payment_event(ORDER, HALF_THE_CAP, later, world),
        )
    )

    assert [verdict.allowed for verdict in verdicts] == [True, True]


def test_a_backdated_payment_never_reaches_the_engine(
    dogwood_binary: Path, tmp_path: Path
) -> None:
    """Refused as a broken trace, not answered as a payment.

    Raised rather than denied: a caller who backdates has asked a question
    Dogwood's contract does not cover, and there is no verdict to report.
    """
    ledger = build_ledger(tmp_path / "payments.log")
    gate = build_gate(dogwood_binary, ledger)
    ledger.record(ORDER, HALF_THE_CAP, BASE + timedelta(hours=1))

    with pytest.raises(EngineUnavailableError, match="do not move forward"):
        gate.decide(ORDER, HALF_THE_CAP, BASE)


def test_the_engine_refills_the_hour_for_a_backdated_payment(
    dogwood_binary: Path, tmp_path: Path
) -> None:
    """What the refusal above is worth, measured.

    A window looks only backwards, so a payment stamped before one already in
    the trace sees none of the payments it should have joined. The engine
    replays events in file order, reports nothing, and exits 0.
    """
    world = read_world(POLICY_DIR)
    trace = tmp_path / "trace.log"
    trace.write_text(
        payment_event(ORDER, HALF_THE_CAP, BASE + timedelta(hours=1), world)
        + "\n"
        + payment_event(ORDER, HALF_THE_CAP, BASE, world)
        + "\n",
        encoding="utf-8",
    )

    done = subprocess.run(  # noqa: S603 (path comes from the fixture, not from input)
        [
            str(dogwood_binary),
            "replay",
            str(POLICY_DIR / POLICY_FILE),
            "--policy-schema",
            str(POLICY_DIR / SCHEMA_FILE),
            "--event-schema",
            str(EVENT_SCHEMA),
            "--trace",
            str(trace),
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    backdated = json.loads(done.stdout)["verdicts"][-1]
    assert backdated["verdict"] == "allow", "the guard would be pointless otherwise"
    assert not backdated["errors"]


def test_a_total_too_large_for_a_long_is_not_an_approval(dogwood_binary: Path) -> None:
    """A sum that cannot be represented must not read as room to spend.

    The engine neither raises on a total outside a Long nor wraps it into
    range: a trace summing past 2**63 still denies, and denies with no errors,
    so a comparison decided it. Unreachable through the gate, where every
    recorded payment is at most the cap, and pinned because the failure mode
    would be an approval.
    """
    cli = _cli(dogwood_binary, own_event_schema=True)
    world = read_world(POLICY_DIR)
    enormous = cents(2**62)

    verdicts = cli.replay(
        (
            payment_event(ORDER, enormous, BASE, world),
            payment_event(ORDER, enormous, BASE + timedelta(minutes=1), world),
            payment_event(ORDER, cents(1), BASE + timedelta(minutes=2), world),
        )
    )

    assert not verdicts[-1].allowed
    assert not verdicts[-1].errors, "denied by the cap, not by a failure to evaluate"


def test_one_refusal_is_worded_one_way(dogwood_binary: Path, tmp_path: Path) -> None:
    """The engine's rule order is not stable, and the sentence must be.

    A payment over both caps comes back naming rules [2, 3] on one replay and
    [3, 2] on the next, for the same input. Repeated rather than asserted once,
    because a single sample often agrees with the unsorted order anyway.
    """
    gate = build_gate(dogwood_binary, build_ledger(tmp_path / "payments.log"))

    worded = {gate.decide(ORDER, cents(15_000), BASE).reason for _ in range(12)}

    assert worded == {
        "denied: a single payment may not exceed $100.00; payments on this order may not "
        "total more than $100.00 in any 60 minutes"
    }


def test_a_ledger_will_not_reopen_a_log_that_already_exists(tmp_path: Path) -> None:
    """Two runs sharing one file would pool their budgets, or silently lose one.

    Starting the log is also what makes its later absence mean something: a file
    that was never created is indistinguishable from an hour with no payments.
    """
    build_ledger(tmp_path / "payments.log")

    with pytest.raises(LedgerUnobtainableError, match="could not start a ledger"):
        build_ledger(tmp_path / "payments.log")
