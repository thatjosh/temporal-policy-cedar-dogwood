"""What an engine answers, in a shape both engines share.

Cedar returns this and Dogwood will. That is not a convenience: the experiment
compares two engines answering the same question, and if each returned its own
result type, every comparison would first have to translate, and the
translation is where a difference could quietly be introduced.
"""

from __future__ import annotations

from dataclasses import dataclass


class EngineUnavailableError(RuntimeError):
    """The engine could not be asked, or its answer could not be trusted.

    Never means "denied". It means no decision exists, which callers must turn
    into a denial themselves. Keeping the two apart matters because they need
    different responses from a human: a denial is the system working, and this
    is the system being broken.
    """


@dataclass(frozen=True)
class Decision:
    """One engine's answer about one proposed payment.

    ``reason`` is free text for a human reading a log. No code branches on it,
    because a caller that parses a reason string has recreated the policy in a
    regex. Tests do assert on fragments of it, because the explanation a refused
    person reads is a deliverable rather than a debug string.
    """

    allowed: bool
    reason: str

    def __bool__(self) -> bool:
        """Refuse to be a condition.

        Any object without this is truthy, so `if gate.decide(...): pay()` would
        pay on every denial. In a payments gate that is the most expensive
        default available, and there is no reading of `if decision:` obvious
        enough to be worth allowing.
        """
        message = "a Decision is not a boolean: check .allowed"
        raise TypeError(message)

    @classmethod
    def allow(cls, reason: str) -> Decision:
        return cls(allowed=True, reason=reason)

    @classmethod
    def deny(cls, reason: str) -> Decision:
        return cls(allowed=False, reason=reason)
