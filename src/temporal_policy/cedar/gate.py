"""Asking Cedar whether a proposed payment may execute.

This module gathers facts; the policy file judges them. No branch here inspects
an amount, which is what makes the policy the complete answer to what the agent
may do.

`build_gate()` in each version package is the seam, and the class stayed shared
across the two versions, but not untouched. A Cedar decision is a function of
the request, the policies and the entity store, and none of those is a payment
log, so v2's rolling total has to arrive as a request-time fact: the `Window`
below, and the branch of `_facts` that puts it in the context. That v2 could not
leave this file alone is part of the measurement.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from cedarpy import (
    AuthzResult,
    Entities,
    PolicySet,
    Schema,
    is_authorized,
    policies_to_json_str,
    validate_policies,
)

from temporal_policy.clock import require_utc
from temporal_policy.decision import Decision, EngineUnavailableError
from temporal_policy.guardrail import Guardrail
from temporal_policy.money import Cents

# The scenario is fixed: one agent, one action, one customer's orders. These are
# constants rather than parameters because varying them would be a different
# experiment, and a knob nobody turns is a knob that goes untested.
AGENT = 'Agent::"support-bot"'
ACTION_PAY = 'Action::"pay"'
ORDER_TYPE = "Order"

POLICY_FILE = "policy.cedar"
SCHEMA_FILE = "payments.cedarschema"
WORLD_FILE = "world.json"


@dataclass(frozen=True)
class Window:
    """What one order has already paid over one span of time.

    Carries the span and the order it was measured over, not just the total, so
    the policy can check that the answer belongs to the payment being judged.
    It still has to take the total on trust; that is the half of the rule Cedar
    cannot hold.
    """

    order_id: str
    start: datetime
    end: datetime
    total_cents: Cents


class LedgerUnavailableError(RuntimeError):
    """A window could not be obtained, so the temporal rule has no input.

    Deliberately not an `EngineUnavailableError`, which says no decision exists.
    Nothing is wrong with the engine here: the gate withholds the fact and a
    rule refuses the payment for want of it (spec case T11).
    """


class WindowSource(Protocol):
    """Where the gate gets history from.

    A protocol because the interesting implementation is not the in-memory one
    in `v2/ledger.py` but the payment database it stands in for, which raises
    the error above rather than always having an answer.
    """

    def window(self, order_id: str, at: datetime) -> Window: ...


class CedarGate:
    """One question: may this payment execute? Answered by the policy files.

    Parsed once at construction, so the engine's cost does not read as the
    rule's.
    """

    def __init__(
        self,
        policy_dir: Path,
        guardrails: tuple[Guardrail, ...],
        windows: WindowSource | None = None,
    ) -> None:
        # Explicit encoding, because the default depends on the machine's locale
        # and a policy file must never read differently on a different machine.
        schema_source = (policy_dir / SCHEMA_FILE).read_text(encoding="utf-8")
        policy_source = (policy_dir / POLICY_FILE).read_text(encoding="utf-8")
        world_source = (policy_dir / WORLD_FILE).read_text(encoding="utf-8")

        # First, because a policy that does not type-check is a more
        # fundamental complaint than a pairing mismatch.
        _require_valid(policy_source, schema_source, policy_dir)

        self._schema = Schema.from_str(schema_source)
        self._policies = PolicySet.from_str(policy_source)
        # Passing the schema validates world.json against it, so a world that
        # does not match the types the policies assume fails here rather than at
        # the first payment.
        self._world = Entities.from_json_str(world_source, schema_source)
        self._explanations = _pair_explanations(policy_source, guardrails)
        self._windows = windows

    def decide(self, order_id: str, amount: Cents, at: datetime) -> Decision:
        """Judge one proposed payment.

        `at` is part of the interface both versions share. v1's rules are not
        temporal, so nothing reads it, but it is still validated so a naive
        datetime is refused identically in both.
        """
        at = require_utc(at)

        request = {
            "principal": AGENT,
            "action": ACTION_PAY,
            "resource": {"type": ORDER_TYPE, "id": order_id},
            "context": self._facts(order_id, amount, at),
        }

        try:
            result = is_authorized(request, self._policies, self._world, schema=self._schema)
            return self._explain(result)
        except Exception as failure:
            # cedarpy raises for arguments it cannot build a request from, such
            # as a non-string order id. Broad, so no foreign exception type
            # leaks to callers; converts to "no decision", never to "allowed".
            message = f"Cedar could not evaluate the request: {failure}"
            raise EngineUnavailableError(message) from failure

    def _facts(self, order_id: str, amount: Cents, at: datetime) -> dict[str, Any]:
        """Everything the policy is allowed to judge on.

        v1 needs one fact. v2 needs a second that Cedar cannot derive, and this
        is where its rule stops being one file: `policy.cedar` holds the cap,
        `v2/ledger.py` computes what it is compared against.

        `amount` is passed through, never coerced: `int("5000")` would turn a
        caller's type error into a payment.
        """
        facts: dict[str, Any] = {"amount_cents": amount}
        if self._windows is None:
            return facts

        try:
            window = self._windows.window(order_id, at)
        except LedgerUnavailableError:
            # Spec case T11, and why the schema makes `window` optional. Omitted
            # rather than filled in: the policy's `has` guard turns an absent
            # window into a refusal, where a zero would be an approval. Only the
            # declared signal is caught, so a broken ledger raises rather than
            # spending the rest of its life denying every payment.
            return facts

        facts["window"] = {
            "order": {"__entity": {"type": ORDER_TYPE, "id": window.order_id}},
            "start": _cedar_datetime(window.start),
            "end": _cedar_datetime(window.end),
            "total_cents": window.total_cents,
        }
        return facts

    def _explain(self, result: AuthzResult) -> Decision:
        """Turn Cedar's diagnostics into the answer the caller sees.

        These branches report; they do not decide. The error check is not a rule
        either: an error means at least one policy was not applied, so no verdict
        exists that every guardrail agreed to.
        """
        diagnostics = result.diagnostics
        errors = [str(error) for error in diagnostics.errors]
        if errors:
            return Decision.deny(
                "denied: the engine could not apply every rule to this request, so no "
                f"verdict exists that all guardrails agreed to ({'; '.join(errors)})"
            )

        annotations = diagnostics.id_annotations_by_reason
        # `reasons` are Cedar's internal policy handles; the annotation map turns
        # each into the `@id` the policy file declares.
        # Sorted because cedarpy does not order `reasons` deterministically, so
        # a two-rule refusal is otherwise worded two ways for the same input.
        rule_ids = sorted(
            str(annotations.get(reason, reason)) for reason in diagnostics.reasons
        )

        if result.allowed:
            return Decision.allow(f"allowed by {', '.join(rule_ids)}: no guardrail objected")
        if not rule_ids:
            return Decision.deny(
                "denied: no policy permits this agent to pay against this order"
            )
        return Decision.deny(
            "denied: " + "; ".join(self._explanations[rule_id] for rule_id in rule_ids)
        )


def _cedar_datetime(at: datetime) -> str:
    """Format an instant the way Cedar's `datetime` literal insists on.

    Narrower than `datetime.isoformat()`: a `+00:00` offset, or a sixth decimal
    place, and Cedar rejects the whole request rather than that one attribute.
    Milliseconds are the finest it takes. Truncating to them leaves the span the
    policy checks intact for any window whose ends differ by a whole number of
    milliseconds, which the ledger's do.
    """
    return require_utc(at).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _declared_ids(policy_source: str) -> frozenset[str]:
    """Every `@id` in the policy file, according to Cedar's own parser.

    Parsed rather than pattern-matched: a regex counts an `@id` written inside a
    comment, and miscounting attaches the wrong explanation to a refusal.
    """
    parsed = json.loads(policies_to_json_str(policy_source))
    if parsed["templates"]:
        message = "policy templates are not supported: every rule must be a static policy"
        raise EngineUnavailableError(message)

    static: dict[str, Any] = parsed["staticPolicies"]
    # Skipped rather than refused, they would be invisible to the pairing check
    # and then named by Cedar with no explanation to look up.
    unnamed = sorted(
        h for h, policy in static.items() if "id" not in policy.get("annotations", {})
    )
    if unnamed:
        message = f"policy declares rules with no @id: {', '.join(unnamed)}"
        raise EngineUnavailableError(message)

    return frozenset(str(policy["annotations"]["id"]) for policy in static.values())


def _pair_explanations(policy_source: str, guardrails: tuple[Guardrail, ...]) -> dict[str, str]:
    """Check the policy file and the explanations describe the same rule set.

    Both directions are errors: an unexplained rule reaches a human as an
    identifier, and an orphaned explanation is a rule someone deleted while
    believing it still applied.
    """
    declared = _declared_ids(policy_source)
    explained = frozenset(guardrail.id for guardrail in guardrails)

    # Two explanations for one rule collapse silently into whichever came last,
    # so the sentence a customer reads would depend on tuple order.
    if len(explained) != len(guardrails):
        message = "the same rule is explained more than once"
        raise EngineUnavailableError(message)

    unexplained = sorted(declared - explained)
    if unexplained:
        message = f"policy declares rules with no explanation: {', '.join(unexplained)}"
        raise EngineUnavailableError(message)

    orphaned = sorted(explained - declared)
    if orphaned:
        listed = ", ".join(orphaned)
        message = f"explanations given for rules the policy does not declare: {listed}"
        raise EngineUnavailableError(message)

    return {guardrail.id: guardrail.explanation for guardrail in guardrails}


def _require_valid(policy_source: str, schema_source: str, policy_dir: Path) -> None:
    """Refuse to serve decisions from a policy that does not type-check.

    A condition that cannot be evaluated is skipped at run time, and a skipped
    guardrail is an absent one.
    """
    result = validate_policies(policy_source, schema_source)
    if not result.validation_passed:
        detail = "; ".join(str(error) for error in result.errors)
        message = f"{policy_dir / POLICY_FILE} does not validate against its schema: {detail}"
        raise EngineUnavailableError(message)
