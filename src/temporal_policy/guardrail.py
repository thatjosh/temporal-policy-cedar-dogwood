"""A rule in a policy file, and how to say it to a human.

Neither engine can tell you in English what a rule means, so the wording lives
beside the policy. Cedar names the rule that refused, so its pairing is by name;
Dogwood names it by position, so its tuple must be in file order. Both gates
check the pairing at construction, so drift is a startup error either way.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Guardrail:
    id: str
    explanation: str
