"""Money, as a type the compiler can tell apart from any other integer.

Always whole cents. A cap of $100.00 that becomes 99.99999999 under one
rounding is a guardrail with a hole in it.
"""

from __future__ import annotations

from typing import NewType

# A NewType rather than a class: the values cross into both engines as plain
# integers, and a wrapper would be unwrapped at every boundary, which is where
# the mistakes happen.
Cents = NewType("Cents", int)


def cents(value: int) -> Cents:
    """Label an integer as money.

    Validates nothing: zero and negative amounts are proposals the policy must
    be given the chance to refuse (spec cases T9 and T10), and refusing them
    here would move a rule out of the policy and into the harness.
    """
    return Cents(value)
