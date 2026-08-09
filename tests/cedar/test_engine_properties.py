"""Cedar behaviours the policy is written around.

Beyond the spec table, and the reason the policy looks the way it does. Each of
these is a counter-example: remove the thing it defends and a guardrail stops
guarding, usually by allowing rather than by failing.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from cedarpy import is_authorized

from temporal_policy.cedar.gate import (
    ACTION_PAY,
    AGENT,
    POLICY_FILE,
    SCHEMA_FILE,
    WORLD_FILE,
    CedarGate,
    Guardrail,
)
from temporal_policy.cedar.v1 import GUARDRAILS, POLICY_DIR, build_gate
from temporal_policy.decision import EngineUnavailableError
from temporal_policy.money import cents
from temporal_policy.spec import BASE, ORDER, UNKNOWN_ORDER


def test_an_unguarded_attribute_read_fails_open() -> None:
    """Why every attribute access in policy.cedar is guarded by `has`.

    Cedar skips a policy whose condition raises, so an unguarded forbid vanishes
    exactly when the data it polices goes missing. The failure mode is a silent
    ALLOW, not an error. This is that counter-example, pinned: if it ever starts
    denying, the guards have stopped earning their keep.
    """
    # Written out here rather than produced by editing policy.cedar. The
    # property belongs to Cedar, not to this repo's rules, and text surgery on
    # the real file silently becomes a no-op the day someone reformats it, at
    # which point this test passes while asserting nothing.
    unguarded = (
        'permit (principal, action == Action::"pay", resource);\n'
        'forbid (principal, action == Action::"pay", resource)\n'
        "unless { context.amount_cents > 0 };"
    )
    request = {
        "principal": AGENT,
        "action": ACTION_PAY,
        "resource": f'Order::"{ORDER}"',
        "context": {},
    }

    result = is_authorized(request, unguarded, (POLICY_DIR / WORLD_FILE).read_text())

    assert result.allowed, "expected the documented fail-open behaviour"
    assert result.diagnostics.errors, "expected Cedar to report the skipped policies"


@pytest.mark.parametrize("malformed", ["5000", None, 1.5, [1]])
def test_a_malformed_amount_is_denied_rather_than_allowed(malformed: object) -> None:
    """An amount that is not money cannot be judged, so the payment cannot proceed.

    Cedar rejects the request against the schema, which means the guardrails
    were never applied to it. The gate refuses to relay a verdict reached that
    way, so the failure direction is DENY. This is what the schema on the
    request buys: without it, a misspelled or mistyped context is evaluated as
    something else rather than refused.
    """
    decision = build_gate().decide(ORDER, malformed, BASE)  # type: ignore[arg-type]

    assert not decision.allowed
    assert "could not apply every rule" in decision.reason


@pytest.mark.parametrize("malformed", [123, None, ["ORD-1"], {"id": "ORD-1"}])
def test_an_order_id_that_is_not_a_string_produces_no_verdict(malformed: object) -> None:
    """Not a denial: no decision at all, which the caller must fail closed on.

    Keeping the two apart matters. A denial is the system working, and this is
    the system being unable to answer.
    """
    with pytest.raises(EngineUnavailableError):
        build_gate().decide(malformed, cents(5_000), BASE)  # type: ignore[arg-type]


def test_a_quote_in_an_order_id_is_data_rather_than_syntax() -> None:
    """Cedar takes a structured request, so there is nothing to inject into.

    The order id travels as a field of an object, never as text spliced into a
    policy or a query, so a quote in it is just an unusual customer reference
    that matches no entity. Worth pinning because the other engine in this
    repo has to serialise the same value into a text grammar, where the same
    input is a very different problem.
    """
    decision = build_gate().decide('ORD-1" or true', cents(5_000), BASE)

    assert not decision.allowed
    assert "no policy permits" in decision.reason


def test_an_order_belonging_to_nobody_is_denied() -> None:
    """Why the permit says `resource in Customer::"cus-100"`.

    An order the entity store has never heard of is in no customer, matches no
    permit, and is denied by default. A bare `resource` would authorise payments
    against order ids that do not exist.
    """
    decision = build_gate().decide(UNKNOWN_ORDER, cents(5_000), BASE)

    assert not decision.allowed
    assert "no policy permits" in decision.reason


def test_a_rule_without_an_explanation_is_refused_at_construction() -> None:
    """A guardrail nobody can explain is caught before it ever refuses anyone."""
    incomplete = tuple(g for g in GUARDRAILS if g.id != "per-payment-cap")

    with pytest.raises(EngineUnavailableError, match="no explanation"):
        CedarGate(POLICY_DIR, incomplete)


def test_an_explanation_for_a_deleted_rule_is_refused_at_construction() -> None:
    """The other direction: an explanation kept for a rule that no longer exists.

    This is the one that matters when a policy is edited, because the stale
    explanation reads as evidence the rule is still there.
    """
    invented = (*GUARDRAILS, Guardrail(id="rule-that-was-deleted", explanation="..."))

    with pytest.raises(EngineUnavailableError, match="does not declare"):
        CedarGate(POLICY_DIR, invented)


def test_a_naive_instant_is_refused() -> None:
    """v1 reads no clock, but it must refuse the same inputs v2 refuses.

    A window measured from an instant with no timezone means something different
    depending on where the process runs.
    """
    with pytest.raises(ValueError, match="timezone-aware"):
        build_gate().decide(ORDER, cents(5_000), BASE.replace(tzinfo=None))


@pytest.mark.parametrize("missing", [POLICY_FILE, SCHEMA_FILE, WORLD_FILE])
def test_every_policy_file_is_required(missing: str, tmp_path: Path) -> None:
    """Each of the three files must fail loudly at construction when absent.

    Pointing at an empty directory would prove only that the first read fails,
    so the other two could be deleted from the constructor unnoticed.
    """
    (_policy_dir_copy(tmp_path) / missing).unlink()

    with pytest.raises(FileNotFoundError):
        CedarGate(tmp_path, GUARDRAILS)


def _policy_dir_copy(destination: Path, extra_policy: str = "") -> Path:
    """A writable copy of the v1 policy directory, optionally with a rule added."""
    for name in (POLICY_FILE, SCHEMA_FILE, WORLD_FILE):
        source = (POLICY_DIR / name).read_text(encoding="utf-8")
        (destination / name).write_text(source, encoding="utf-8")
    if extra_policy:
        policy = destination / POLICY_FILE
        policy.write_text(policy.read_text(encoding="utf-8") + extra_policy)
    return destination


@pytest.mark.parametrize(
    ("order_id", "amount", "expected"),
    [
        (ORDER, 0, "positive"),
        (ORDER, 10_001, "$100.00"),
        (UNKNOWN_ORDER, 5_000, "no policy permits"),
    ],
)
def test_each_rule_is_explained_by_its_own_sentence(
    order_id: str, amount: int, expected: str
) -> None:
    """The pairing check proves the id sets match, not that the pairs are right.

    Without this, two explanations can be swapped and every test still passes,
    so someone refused for paying nothing is told the agent may not pay against
    that order. One input per rule, each tripping exactly that rule.
    """
    decision = build_gate().decide(order_id, cents(amount), BASE)

    assert not decision.allowed
    assert expected in decision.reason


def test_a_rule_with_no_id_is_refused_at_construction(tmp_path: Path) -> None:
    """A rule Cedar can name in a denial but we cannot explain.

    Skipping unnamed rules instead of refusing them hides them from the pairing
    check, and the first payment that trips one dies with a KeyError, which is
    neither a decision nor an engine error.
    """
    unnamed = (
        '\nforbid (principal, action == Action::"pay", resource)\n'
        "unless { context has amount_cents && context.amount_cents != 4242 };\n"
    )

    with pytest.raises(EngineUnavailableError, match="no @id"):
        CedarGate(_policy_dir_copy(tmp_path, unnamed), GUARDRAILS)


def test_the_same_rule_explained_twice_is_refused() -> None:
    """Otherwise the sentence a refused person reads depends on tuple order."""
    duplicated = (*GUARDRAILS, Guardrail(id="per-payment-cap", explanation="something else"))

    with pytest.raises(EngineUnavailableError, match="more than once"):
        CedarGate(POLICY_DIR, duplicated)


def test_a_decision_cannot_be_used_as_a_condition() -> None:
    """`if gate.decide(...): pay()` must not pay on a denial.

    Any object without __bool__ is truthy, so the obvious-looking condition is
    the expensive one. Refusing outright beats guessing which reading was meant.
    """
    refused = build_gate().decide(ORDER, cents(15_000), BASE)

    with pytest.raises(TypeError, match="not a boolean"):
        bool(refused)
