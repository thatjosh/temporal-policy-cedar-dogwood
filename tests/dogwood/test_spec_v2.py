"""Dogwood v2 against the shared case table, read down the v2 column.

The same table Cedar is judged by, driven the same way. Every verdict here is
the engine's: the rolling total is summed inside `pay.dw`, and the ledger passed
to `run_case` is the log it sums, not a number computed for it.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from temporal_policy.dogwood.v2 import build_gate, build_ledger
from temporal_policy.money import cents
from temporal_policy.spec import BASE, CASES, ORDER, Case, run_case


@pytest.mark.parametrize("case", CASES, ids=lambda case: f"{case.id}-{case.pins_down}")
def test_spec_case(case: Case, dogwood_binary: Path, tmp_path: Path) -> None:
    ledger = build_ledger(tmp_path / "payments.log")
    gate = build_gate(dogwood_binary, ledger)

    assert run_case(case, gate.decide, ledger.record) == list(case.v2)


def test_a_log_that_has_gone_missing_denies(dogwood_binary: Path, tmp_path: Path) -> None:
    """Spec case T11, which the table cannot hold because it has no verdict column.

    An unreadable log is not a quiet hour, but it looks like one to the engine:
    the sum over no matching event is zero, and zero is under every cap. Nothing
    expressible in `pay.dw` can tell the two apart, so failing closed has to
    happen here.
    """
    log = tmp_path / "payments.log"
    ledger = build_ledger(log)
    gate = build_gate(dogwood_binary, ledger)
    ledger.record(ORDER, cents(5_000), BASE)
    log.unlink()

    decision = gate.decide(ORDER, cents(1_000), BASE + timedelta(minutes=1))

    assert not decision.allowed
    assert "could not be read" in decision.reason


@pytest.mark.parametrize(
    ("tampered", "why"),
    [("", "every line deleted"), ("one line\nand another\n", "a line we did not write")],
    ids=["truncated", "padded"],
)
def test_a_log_that_is_not_the_one_we_wrote_denies(
    tampered: str, why: str, dogwood_binary: Path, tmp_path: Path
) -> None:
    """Losing lines refills the budget; gaining them is evidence of nothing.

    Neither is visible to the engine, which sums whatever it is handed. Counting
    our own writes is the only reading of the log that can notice.
    """
    log = tmp_path / "payments.log"
    ledger = build_ledger(log)
    gate = build_gate(dogwood_binary, ledger)
    ledger.record(ORDER, cents(5_000), BASE)
    log.write_text(tampered, encoding="utf-8")

    decision = gate.decide(ORDER, cents(1_000), BASE + timedelta(minutes=1))

    assert not decision.allowed
    assert "were recorded through it" in decision.reason
