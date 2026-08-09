"""What an engine answers, in a shape both engines share.

Not a convenience: if each returned its own type, every comparison would have
to translate first, and the translation is where a difference could hide.
"""

from __future__ import annotations

from dataclasses import dataclass


class EngineUnavailableError(RuntimeError):
    """The engine could not be asked, or its answer could not be trusted.

    Never means "denied". A denial is the system working; this is the system
    being broken, and they need different responses from a human.
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

        Without this, `if gate.decide(...): pay()` pays on every denial, and no
        reading of `if decision:` is obvious enough to be worth allowing.
        """
        message = "a Decision is not a boolean: check .allowed"
        raise TypeError(message)

    @classmethod
    def allow(cls, reason: str) -> Decision:
        return cls(allowed=True, reason=reason)

    @classmethod
    def deny(cls, reason: str) -> Decision:
        return cls(allowed=False, reason=reason)
