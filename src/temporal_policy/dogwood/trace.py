"""Rendering a payment as a line of a Dogwood event trace.

Dogwood evaluates a trace file, so every value has to be serialised into a text
grammar first. Cedar takes a structured request and has nothing to serialise
into, which is the sharpest difference between the two.
"""

from __future__ import annotations

import re
from datetime import datetime

from temporal_policy.clock import require_utc
from temporal_policy.decision import EngineUnavailableError
from temporal_policy.money import Cents

AGENT = 'Support::Agent::"support-bot"'
ACTION_PAY = 'Support::Action::"Pay"'
ORDER_TYPE = "Support::Order"

# Letters, digits, and the three separators an order reference realistically
# uses. Everything the trace parser treats as punctuation is outside this set.
_SAFE_IDENTIFIER = re.compile(r"\A[A-Za-z0-9_.-]{1,256}\Z")


def check_identifier(value: object, *, field: str) -> str:
    """Refuse any identifier that could reach the parser as syntax.

    Rejected rather than escaped, which is worth justifying because Dogwood
    ships an escaper. It renders ids with Rust's ``escape_debug``, which handles
    quotes and control characters but leaves printable ASCII alone. ``scope(...)``
    is closed by a plain search for the first ``)``, so a parenthesis in an id
    ends the scope early however carefully it was escaped.

    Measured against dogwood 1.0.0: a ``)`` makes the line unparseable, a
    newline splits it, and a raw ``"`` lets the rest of the value be read as
    trace syntax, which turned a refused payment into an approved one. An
    allowlist excludes all of them without depending on our reading of an
    escaper matching the parser's.
    """
    if not isinstance(value, str) or not _SAFE_IDENTIFIER.fullmatch(value):
        message = (
            f"{field} {value!r} is not a usable Dogwood identifier. "
            "Allowed: letters, digits, underscore, dot and hyphen, up to 256 characters. "
            "Refused rather than escaped, because Dogwood's scope(...) is delimited by a "
            "plain search for ')' that no escaping can protect."
        )
        raise EngineUnavailableError(message)
    return value


def check_amount(amount: object) -> int:
    """Refuse anything that is not already a whole number of cents.

    Never coerced: ``int(10000.9)`` is 10000, exactly the cap, so a float from a
    JSON tool call would be truncated into an approval. ``bool`` is excluded
    separately, being a subclass of ``int``.

    Dogwood renders into text before the engine sees anything, so this has to be
    caught here, while Cedar hands the value over and lets the schema reject it.
    So the two answer differently: Cedar denies, having got a verdict of a kind,
    and this raises, no engine having been asked.
    """
    if isinstance(amount, bool) or not isinstance(amount, int):
        message = (
            f"amount {amount!r} is not a whole number of cents. "
            "Refused rather than converted, because rounding a payment into range "
            "is how an over-cap amount becomes an approved one."
        )
        raise EngineUnavailableError(message)
    return amount


def payment_event(order_id: str, amount: Cents, at: datetime, world: str) -> str:
    """One executed or proposed payment, as a trace line.

    ``request_context`` is what a ``context.*`` reference reads. The trailing
    group is the event's own record, which a temporal predicate matches on; v1
    has no such predicate.

    ``world`` is the entity store, inlined into every event. Cedar loads one
    once at construction; Dogwood has nowhere to put one, so it is repeated on
    every line, which is a cost worth seeing.
    """
    order = f'{ORDER_TYPE}::"{check_identifier(order_id, field="order id")}"'
    payload = f"input: {{ amount_cents: {check_amount(amount)} }}"
    return (
        f"@{_epoch_seconds(at)} "
        f"scope(principal: {AGENT}, resource: {order}) "
        f"{world} "
        f"request_context({payload}) "
        f"{ACTION_PAY}::request({payload})"
    )


def _epoch_seconds(at: datetime) -> int:
    """Dogwood timestamps are whole seconds since the epoch."""
    return int(require_utc(at).timestamp())
