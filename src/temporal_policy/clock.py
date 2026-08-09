"""When a payment is judged to happen.

Time is a parameter everywhere in this repo, never a call to the wall clock.
Two reasons. Tests need to place payments minutes apart without waiting, and a
rolling window is only meaningful if the instant it is measured from is chosen
by the harness rather than by whatever is asking.
"""

from __future__ import annotations

from datetime import UTC, datetime


def require_utc(at: datetime) -> datetime:
    """Accept only an aware instant, and normalise it to UTC.

    A naive datetime is refused rather than assumed to be local or assumed to
    be UTC. Guessing would make a rolling window mean different things on a
    developer's laptop and on a CI runner in another timezone, and the failure
    would be a wrong verdict rather than an error anyone notices.
    """
    if at.tzinfo is None or at.tzinfo.utcoffset(at) is None:
        message = f"instant must be timezone-aware, got {at!r}"
        raise ValueError(message)
    try:
        return at.astimezone(UTC)
    except OverflowError as failure:
        # datetime.min and datetime.max overflow when shifted between offsets.
        # Re-raised as ValueError so a caller of this function has one exception
        # type to handle rather than two.
        message = f"instant cannot be expressed in UTC: {at!r}"
        raise ValueError(message) from failure
