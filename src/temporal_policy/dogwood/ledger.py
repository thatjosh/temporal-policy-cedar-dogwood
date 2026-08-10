"""The log of payments that executed, which is what the rolling cap sums.

Dogwood keeps no event store between runs and `replay` reads a whole trace, so
the history a temporal rule needs is handed to the engine again on every
decision. This is that history.

Only executed payments belong in it. A trace event carries no verdict, so the
sum cannot tell a payment that moved money from one that was refused.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from temporal_policy.decision import EngineUnavailableError
from temporal_policy.dogwood.trace import payment_event
from temporal_policy.money import Cents


class LedgerUnobtainableError(EngineUnavailableError):
    """The log could not be produced, or could not be produced in full.

    Its own type because it is the one failure a gate answers with a denial
    instead of raising: an engine that cannot be asked is broken, while a log
    that cannot be read is a fact missing from the payment.
    """


class Ledger:
    """Payments that executed, as the trace lines the engine will replay.

    Lines rather than amounts, so that what is replayed is what was written.
    """

    def __init__(self, path: Path, world: str) -> None:
        """Start an empty log, refusing to reuse one that already exists.

        The file exists from here on, so its later absence means the log was
        lost rather than that no payment was made.
        """
        self._path = path
        self._world = world
        self._recorded = 0
        try:
            path.touch(exist_ok=False)
        except OSError as failure:
            message = f"could not start a ledger at {path}: {failure}"
            raise LedgerUnobtainableError(message) from failure

    def record(self, order_id: str, amount: Cents, at: datetime) -> None:
        """Log one payment that executed. Never one that was refused."""
        event = payment_event(order_id, amount, at, self._world)
        try:
            with self._path.open("a", encoding="utf-8") as log:
                log.write(event + "\n")
        except OSError as failure:
            message = f"could not record a payment in {self._path}: {failure}"
            raise LedgerUnobtainableError(message) from failure
        self._recorded += 1

    def events(self) -> tuple[str, ...]:
        """Every payment so far, or a refusal to guess at the rest.

        A short log reads to the engine exactly like a quiet hour: the sum over
        no matching event is zero, which is under every cap. Counting our own
        writes is what notices. It cannot notice a line edited in place, which
        needs an append-only or signed store.
        """
        try:
            lines = tuple(self._path.read_text(encoding="utf-8").splitlines())
        except OSError as failure:
            message = f"ledger {self._path} could not be read: {failure}"
            raise LedgerUnobtainableError(message) from failure
        if len(lines) != self._recorded:
            message = (
                f"ledger {self._path} holds {len(lines)} events, but {self._recorded} "
                "payments were recorded through it"
            )
            raise LedgerUnobtainableError(message)
        return lines
