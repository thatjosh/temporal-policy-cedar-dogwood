"""Asking Dogwood whether a proposed payment may execute.

Same job as the Cedar gate, the same answer type, and deliberately the same
policy shape, so the comparison measures the rule rather than two ways of
writing it.

The mechanics differ. `replay` is the only evaluator the CLI exposes, and it
decides a whole trace at once, so one decision is a replay of a trace whose
last line is the proposed payment. In v1 that trace is one line; in v2 it
becomes the whole ledger, which is where the shape starts to cost something.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from temporal_policy.decision import Decision, EngineUnavailableError
from temporal_policy.dogwood.cli import DogwoodCli, Verdict
from temporal_policy.dogwood.trace import payment_event
from temporal_policy.guardrail import Guardrail
from temporal_policy.money import Cents

POLICY_FILE = "pay.dw"
SCHEMA_FILE = "schema.cedarschema"
WORLD_FILE = "world.dwentities"


class DogwoodGate:
    """One question: may this payment execute? Answered by the policy file."""

    def __init__(
        self, binary: Path, policy_dir: Path, guardrails: tuple[Guardrail, ...]
    ) -> None:
        # In file order, because a verdict names its rule by position. That much
        # the engine forces; checking the two agree is ours to do, and happens
        # at the end of this constructor.
        self._guardrails = guardrails
        self._world = (policy_dir / WORLD_FILE).read_text(encoding="utf-8").strip()
        self._cli = DogwoodCli(
            binary=binary,
            policy=policy_dir / POLICY_FILE,
            schemas=("--policy-schema", str(policy_dir / SCHEMA_FILE)),
        )
        _require_matching_rules(self._cli.declared_rule_ids(), guardrails, policy_dir)

    def decide(self, order_id: str, amount: Cents, at: datetime) -> Decision:
        """Judge one proposed payment.

        A failure to reach a verdict is raised, never returned as a denial: a
        caller that confuses the two will either retry a refusal forever or read
        a broken engine as permission.
        """
        event = payment_event(order_id, amount, at, self._world)
        # `[-1]` reads the proposed payment's verdict. v1 sends a single event, so
        # this is indistinguishable from `[0]` and no v1 test can tell them
        # apart; `DogwoodCli.replay` is where the ordering is pinned. It starts
        # mattering in v2, where the ledger precedes the proposal.
        return self._explain(self._cli.replay((event,))[-1])

    def _explain(self, verdict: Verdict) -> Decision:
        """Turn one verdict into the answer a caller sees.

        Errors are checked before the verdict, and that ordering is the
        guardrail: Dogwood returns `allow` with a populated `errors` array when
        a forbid fails to evaluate, and a skipped forbid is an absent one.
        """
        if verdict.errors:
            return Decision.deny(
                "denied: the engine could not apply every rule to this payment, so no "
                f"verdict exists that all of them agreed to ({'; '.join(verdict.errors)})"
            )

        named = [self._name_of(index) for index in verdict.determining_rules]
        if verdict.allowed:
            joined = ", ".join(rule.id for rule in named)
            return Decision.allow(f"allowed by {joined}: no guardrail objected")
        if not named:
            # Nothing permitted the payment, so no rule refused it and the
            # engine has none to name. Cedar reaches the same state for an
            # unknown order and says the same thing.
            return Decision.deny(
                "denied: no policy permits this agent to pay against this order"
            )
        return Decision.deny("denied: " + "; ".join(rule.explanation for rule in named))

    def _name_of(self, index: int) -> Guardrail:
        """The rule at a position in the policy file.

        Positional because a verdict identifies its rule by index. Called before
        the allow branch, so drift raises rather than quietly approving.
        """
        if not 0 <= index < len(self._guardrails):
            message = (
                f"`dogwood replay` named rule {index}, but the policy is declared as having "
                f"{len(self._guardrails)}: {POLICY_FILE} and its rule list have drifted"
            )
            raise EngineUnavailableError(message)
        return self._guardrails[index]


def _require_matching_rules(
    declared: tuple[str, ...], guardrails: tuple[Guardrail, ...], policy_dir: Path
) -> None:
    """The policy file and the declared rules must agree, in order.

    A rule inserted, removed or reordered in one place and not the other does
    not fail; it reports a neighbour's explanation to whoever was refused. A
    rename shifts nothing and misattributes nothing, and is caught here anyway
    because this tuple is meant to document the file. Positional identification
    is forced by the engine; leaving the two unchecked was not.
    """
    named = tuple(guardrail.id for guardrail in guardrails)
    if declared != named:
        message = (
            f"{policy_dir / POLICY_FILE} declares rules {declared}, but this version "
            f"declares {named}. A verdict names its rule by position, so these must "
            "match exactly and in order."
        )
        raise EngineUnavailableError(message)
