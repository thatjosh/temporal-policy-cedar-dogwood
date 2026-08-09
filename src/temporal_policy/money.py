"""Money, as a type the compiler can tell apart from any other integer.

Money is always whole cents. No float ever touches an amount: a cap of $100.00
that becomes 99.99999999 under one rounding is a guardrail with a hole in it,
and this arithmetic decides whether payments happen.
"""

from __future__ import annotations

from typing import NewType

# A distinct type, so a function taking Cents cannot be handed a count, an index
# or a duration by mistake. It is a NewType rather than a class because the
# values cross into the policy engines as plain integers, and a wrapper would
# have to be unwrapped at every boundary, which is where the mistakes happen.
Cents = NewType("Cents", int)


def cents(value: int) -> Cents:
    """Label an integer as money.

    Validates nothing: zero and negative amounts are proposals the policy must
    be given the chance to refuse (spec cases T9 and T10), and refusing them
    here would move a rule out of the policy and into the harness.
    """
    return Cents(value)
