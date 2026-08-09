"""Dogwood behaviours the harness is written around.

Beyond the spec table. Each of these is a counter-example: remove the thing it
defends and the engine either stops being asked the question we think it is
being asked, or answers a different one.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from temporal_policy.decision import EngineUnavailableError
from temporal_policy.dogwood.cli import DogwoodCli, parse_verdicts
from temporal_policy.dogwood.gate import SCHEMA_FILE, WORLD_FILE, DogwoodGate
from temporal_policy.dogwood.trace import check_identifier, payment_event
from temporal_policy.dogwood.v1 import GUARDRAILS, POLICY_DIR, build_gate
from temporal_policy.guardrail import Guardrail
from temporal_policy.money import cents
from temporal_policy.spec import BASE, ORDER, UNKNOWN_ORDER


def _injection(world: str) -> str:
    """An order id that rewrites the rest of the trace line.

    The raw quote closes the id, the parenthesis closes `scope(` early, and
    everything after is read as trace syntax: a fresh entity store so the
    resource still resolves, then a one cent payment. The engine judges that
    instead of the real amount.
    """
    return (
        f'ORD-1" ) {world} request_context(input: {{ amount_cents: 1 }}) '
        'Support::Action::"Pay"::request(input: { amount_cents: 1 }'
    )


def test_the_engine_approves_an_over_cap_payment_when_the_id_is_crafted(
    dogwood_binary: Path,
) -> None:
    """The attack, proven against the engine rather than asserted about it.

    This is what makes the refusal in the next test worth anything. Without it
    the suite would show only that the harness rejects a peculiar string, and
    would keep passing if the underlying hole were ever closed upstream, or if
    it had never existed.
    """
    cli = DogwoodCli(
        binary=dogwood_binary,
        policy=POLICY_DIR / "pay.dw",
        schemas=("--policy-schema", str(POLICY_DIR / SCHEMA_FILE)),
    )
    world = (POLICY_DIR / WORLD_FILE).read_text(encoding="utf-8").strip()
    agent = 'Support::Agent::"support-bot"'
    over_the_cap = "input: { amount_cents: 999999 }"

    def line(order_id: str) -> str:
        return (
            f'@1786910400 scope(principal: {agent}, resource: Support::Order::"{order_id}") '
            f"{world} request_context({over_the_cap}) "
            f'Support::Action::"Pay"::request({over_the_cap})'
        )

    assert not cli.replay((line("ORD-1"),))[0].allowed, "the honest payment must be refused"
    assert cli.replay((line(_injection(world)),))[0].allowed, "the crafted id must slip through"


def test_the_crafted_id_never_reaches_the_engine(dogwood_binary: Path) -> None:
    """Refused before the engine is asked, so there is no verdict to be wrong.

    Dogwood evaluates a text trace, so an order id is serialised into a grammar
    rather than passed as a structured field. Cedar takes a structured request
    and has nothing to inject into, which is the difference this pair records.
    """
    world = (POLICY_DIR / WORLD_FILE).read_text(encoding="utf-8").strip()

    with pytest.raises(EngineUnavailableError, match="not a usable Dogwood identifier"):
        build_gate(dogwood_binary).decide(_injection(world), cents(999_999), BASE)


@pytest.mark.parametrize(
    ("hostile", "why"),
    [
        ('ORD"1', "a raw quote closes the id and injects the rest"),
        ("ORD)1", "a parenthesis ends scope(...) early, which escaping cannot prevent"),
        ("ORD\n1", "a newline splits the line in two"),
        ("ORD 1", "whitespace separates trace tokens"),
        ("ORD\\1", "a backslash is the escape character"),
        ("", "an empty id names no entity"),
        ("O" * 257, "longer than the allowed bound"),
    ],
)
def test_an_identifier_that_could_be_read_as_syntax_is_refused(hostile: str, why: str) -> None:
    """Every character the trace parser treats as punctuation, refused by name."""
    with pytest.raises(EngineUnavailableError, match="not a usable Dogwood identifier"):
        check_identifier(hostile, field="order id")


def test_a_parenthesis_defeats_escaping_even_though_a_quote_does_not() -> None:
    """Why an allowlist, and not Dogwood's own escaper.

    Dogwood renders ids with Rust's `escape_debug`, which neutralises quotes
    and backslashes but leaves printable ASCII alone. A parenthesis is
    printable, and `scope(...)` is closed by a plain search for the first one,
    so no amount of escaping keeps it out of the grammar. That asymmetry is the
    whole argument for refusing instead.
    """
    with pytest.raises(EngineUnavailableError):
        check_identifier("ORD)1", field="order id")


def test_a_short_replay_is_refused_rather_than_read_as_a_verdict(
    dogwood_binary: Path,
) -> None:
    """`dogwood replay` exits 0 when it returns fewer verdicts than events.

    An event it does not read as a decision point contributes nothing, with no
    error and no warning. Asking it to decide two payments and accepting one
    answer would silently attribute one payment's verdict to another.
    """
    cli = DogwoodCli(
        binary=dogwood_binary,
        policy=POLICY_DIR / "pay.dw",
        schemas=("--policy-schema", str(POLICY_DIR / SCHEMA_FILE)),
    )
    world = (POLICY_DIR / WORLD_FILE).read_text(encoding="utf-8").strip()
    payment = payment_event(ORDER, cents(5_000), BASE, world)
    # A well formed event of a kind the default schema treats as history rather
    # than as a decision point. Verified: this trace returns one verdict for two
    # events, and exits 0.
    history_only = (
        '@1786910401 scope(principal: Support::Agent::"support-bot", '
        'resource: Support::Order::"ORD-1") Support::Action::"Pay"::response()'
    )

    with pytest.raises(EngineUnavailableError, match="verdicts for 2 events"):
        cli.replay((payment, history_only))


def test_a_policy_the_validator_rejects_never_serves_a_decision(
    dogwood_binary: Path, tmp_path: Path
) -> None:
    """`replay` does not validate, so something else has to.

    A policy the validator rejects still replays and emits confident verdicts,
    which is a green test run against a rule that does not typecheck.
    """
    (tmp_path / "pay.dw").write_text(
        '@id("broken")\npermit (principal, action, resource) when { context.nonexistent };\n',
        encoding="utf-8",
    )
    (tmp_path / SCHEMA_FILE).write_text(
        (POLICY_DIR / SCHEMA_FILE).read_text(encoding="utf-8"), encoding="utf-8"
    )

    with pytest.raises(
        EngineUnavailableError, match="rejected by `dogwood validate`"
    ) as failure:
        DogwoodCli(
            binary=dogwood_binary,
            policy=tmp_path / "pay.dw",
            schemas=("--policy-schema", str(tmp_path / SCHEMA_FILE)),
        )

    # `validate` puts a type-check failure on stdout and a parse failure on
    # stderr, so the detail has to read both or the reason is silently dropped.
    assert "nonexistent" in str(failure.value)


@pytest.mark.parametrize(
    "malformed",
    ["", "not json", '{"no_verdicts_key": []}', '{"verdicts": [{"verdict": "allow"}]}'],
)
def test_unreadable_engine_output_is_refused_at_the_boundary(malformed: str) -> None:
    """The CLI emits no version field, so a change of shape has to fail here.

    Parsed in one place, so a future output change is one clear error rather
    than a KeyError from inside a decision.
    """
    with pytest.raises(EngineUnavailableError, match="could not read"):
        parse_verdicts(malformed)


def test_a_naive_instant_is_refused(dogwood_binary: Path) -> None:
    """Both engines refuse the same input, for the same reason."""
    with pytest.raises(ValueError, match="timezone-aware"):
        build_gate(dogwood_binary).decide(ORDER, cents(5_000), BASE.replace(tzinfo=None))


def test_an_order_belonging_to_nobody_is_denied(dogwood_binary: Path) -> None:
    """Why the permit says `resource in Support::Customer::"cus-100"`.

    An order the entity store has never heard of is in no customer, matches no
    permit, and is denied by default. A bare `resource` would authorise payments
    against order ids that do not exist, and the order id is the one field the
    agent controls. The Cedar half makes the same assertion.
    """
    decision = build_gate(dogwood_binary).decide(UNKNOWN_ORDER, cents(5_000), BASE)

    assert not decision.allowed
    assert "no policy permits" in decision.reason


@pytest.mark.parametrize("malformed", [10_000.9, True, "5000", None, 1.5])
def test_an_amount_that_is_not_whole_cents_is_refused(
    malformed: object, dogwood_binary: Path
) -> None:
    """Refused, never rounded.

    `int(10000.9)` is 10000, which is exactly the cap, so converting instead of
    refusing turns an over-cap payment into an approved one. `True` is an `int`
    subclass and would render as a payment of one cent.
    """
    with pytest.raises(EngineUnavailableError, match="not a whole number of cents"):
        build_gate(dogwood_binary).decide(ORDER, malformed, BASE)  # type: ignore[arg-type]


def test_a_verdict_reached_with_a_rule_skipped_is_refused(dogwood_binary: Path) -> None:
    """The errors-before-verdict branch, which is the only fail-open guard.

    Dogwood folds an evaluation error into the decision instead of raising, and
    a rule that could not be evaluated is a rule that did not apply. An amount
    outside a signed 64-bit integer renders as a literal Dogwood reads as a
    string, so the comparisons error and the cap never runs.
    """
    decision = build_gate(dogwood_binary).decide(ORDER, cents(2**63), BASE)

    assert not decision.allowed
    assert "could not apply every rule" in decision.reason


@pytest.mark.parametrize(
    "verdict", ['{"verdicts": [{"verdict": "maybe", "determining_rules": [], "errors": []}]}']
)
def test_an_unknown_verdict_string_is_refused(verdict: str) -> None:
    """Two verdicts exist. A third means the output shape changed.

    Without this it is silently not-an-allow, which reads as a denial today and
    would become an approval under a one character change to `Verdict.allowed`.
    """
    with pytest.raises(EngineUnavailableError, match="unknown verdict"):
        parse_verdicts(verdict)


def test_an_event_containing_a_newline_is_refused(dogwood_binary: Path) -> None:
    """One event must be one line, or the count check compares two unlike things.

    An embedded newline makes one event contribute two verdicts, which cancels
    against an event that contributes none, leaving the count equal and the last
    verdict belonging to something else.
    """
    cli = DogwoodCli(
        binary=dogwood_binary,
        policy=POLICY_DIR / "pay.dw",
        schemas=("--policy-schema", str(POLICY_DIR / SCHEMA_FILE)),
    )

    with pytest.raises(EngineUnavailableError, match="not a single trace event"):
        cli.replay(("@1 scope() a()\n@2 scope() b()",))


@pytest.mark.parametrize(
    "drifted",
    [
        GUARDRAILS[:2],
        (*GUARDRAILS, Guardrail(id="invented", explanation="...")),
        (GUARDRAILS[1], GUARDRAILS[0], GUARDRAILS[2]),
        (GUARDRAILS[0], GUARDRAILS[1], Guardrail(id="renamed", explanation="...")),
    ],
    ids=["too-few", "too-many", "reordered", "renamed"],
)
def test_a_rule_list_that_does_not_match_the_policy_is_refused(
    drifted: tuple[Guardrail, ...], dogwood_binary: Path
) -> None:
    """Drift between `pay.dw` and the rule tuple is a startup error.

    A verdict names its rule by position, so a rule renamed, inserted or
    reordered in one place and not the other does not fail: it reports a
    neighbour's explanation to whoever was refused. The engine emits the ids in
    source order, so the two can be compared before any payment is judged.
    """
    with pytest.raises(EngineUnavailableError, match="must match exactly and in order"):
        DogwoodGate(dogwood_binary, POLICY_DIR, drifted)


@pytest.mark.parametrize(
    ("order_id", "amount", "expected"),
    [
        (ORDER, 0, "positive"),
        (ORDER, 10_001, "$100.00"),
        (UNKNOWN_ORDER, 5_000, "no policy permits"),
    ],
)
def test_each_rule_is_explained_by_its_own_sentence(
    order_id: str, amount: int, expected: str, dogwood_binary: Path
) -> None:
    """The rule check proves the ids match, not that the pairs are right.

    Without this, two explanations can be swapped and every test still passes,
    so someone refused for paying nothing is told the agent may not pay against
    that order. The Cedar suite makes the identical assertion.
    """
    decision = build_gate(dogwood_binary).decide(order_id, cents(amount), BASE)

    assert not decision.allowed
    assert expected in decision.reason


@pytest.mark.parametrize("malformed", [123, None, ["ORD-1"], {"id": "ORD-1"}])
def test_an_order_id_that_is_not_a_string_produces_no_verdict(
    malformed: object, dogwood_binary: Path
) -> None:
    """Refused as "no decision", the same signal Cedar gives for the same input.

    Without the isinstance arm this raises TypeError out of the regex, which is
    not the exception a caller is told to fail closed on.
    """
    with pytest.raises(EngineUnavailableError, match="not a usable Dogwood identifier"):
        build_gate(dogwood_binary).decide(malformed, cents(5_000), BASE)  # type: ignore[arg-type]


def test_the_instant_is_written_into_the_trace_line() -> None:
    """The timestamp is inert in v1 and is the rule itself in v2.

    Pinned now, while it costs one assertion, because a trace whose timestamps
    were all zero would pass every other test in this suite. No engine needed:
    this is about what we render, not what Dogwood does with it.
    """
    world = (POLICY_DIR / WORLD_FILE).read_text(encoding="utf-8").strip()

    event = payment_event(ORDER, cents(5_000), BASE, world)

    assert event.startswith(f"@{int(BASE.timestamp())} ")


def test_the_logged_record_carries_the_same_amount_as_the_context() -> None:
    """A temporal predicate matches the logged record, not the request context.

    They agree today only by construction. If they ever diverge, v1 keeps
    passing and v2's window silently sums a different number from the one the
    per-payment cap judged.
    """
    world = (POLICY_DIR / WORLD_FILE).read_text(encoding="utf-8").strip()

    event = payment_event(ORDER, cents(4_242), BASE, world)

    assert event.count("amount_cents: 4242") == 2


def test_replay_returns_verdicts_in_event_order(dogwood_binary: Path) -> None:
    """One verdict per event, in the order the events were written.

    `decide` relies on this when it reads `verdicts[-1]`, and v1 cannot pin
    that directly because it sends a single event. This pins the property the
    gate depends on, at the level where more than one event exists.
    """
    cli = DogwoodCli(
        binary=dogwood_binary,
        policy=POLICY_DIR / "pay.dw",
        schemas=("--policy-schema", str(POLICY_DIR / SCHEMA_FILE)),
    )
    world = (POLICY_DIR / WORLD_FILE).read_text(encoding="utf-8").strip()
    allowed = payment_event(ORDER, cents(5_000), BASE, world)
    refused = payment_event(ORDER, cents(15_000), BASE.replace(minute=1), world)

    verdicts = cli.replay((allowed, refused))

    assert [v.allowed for v in verdicts] == [True, False]
    assert not verdicts[-1].allowed


def test_an_engine_that_never_answers_is_given_up_on(tmp_path: Path) -> None:
    """A hung subprocess must not hang the gate.

    Cedar runs in-process and cannot fail this way, so the timeout is a cost of
    driving Dogwood as a child process rather than a shared concern. Driven
    through a stand-in that sleeps, with a short timeout, so the test proves the
    path is wired without waiting the real one out.
    """
    sleeper = tmp_path / "dogwood"
    sleeper.write_text("#!/bin/sh\nsleep 30\n", encoding="utf-8")
    sleeper.chmod(0o755)

    with pytest.raises(EngineUnavailableError, match="did not answer"):
        DogwoodCli(
            binary=sleeper,
            policy=POLICY_DIR / "pay.dw",
            schemas=("--policy-schema", str(POLICY_DIR / SCHEMA_FILE)),
            timeout_seconds=0.2,
        )


def test_an_allowed_payment_names_the_rule_that_permitted_it(dogwood_binary: Path) -> None:
    """The wording of an allow, which no test asserted in either engine.

    Both engines emit the same sentence for the same decision, and that is the
    claim the aligned rule ids exist to make true. Held by nothing until now, so
    a spelling change in either policy would have gone unnoticed.
    """
    allowed = build_gate(dogwood_binary).decide(ORDER, cents(5_000), BASE)

    assert allowed.allowed
    assert allowed.reason == "allowed by agent-may-pay: no guardrail objected"


def test_a_negative_amount_reaches_the_engine_unmangled() -> None:
    """The harness must not quietly move an amount into range.

    T9 and T10 produce the same verdict and the same sentence, so a `cents()`
    that clamped negatives to zero would be invisible in both suites. v2's
    rolling sum depends on the number the engine sees being the number asked
    about.
    """
    world = (POLICY_DIR / WORLD_FILE).read_text(encoding="utf-8").strip()

    event = payment_event(ORDER, cents(-5_000), BASE, world)

    assert event.count("amount_cents: -5000") == 2


def test_a_failing_replay_reports_the_trace_it_choked_on(dogwood_binary: Path) -> None:
    """The engine's diagnostics cite a line number and never the input.

    The trace lives in a temporary directory that is gone by the time a caller
    sees the error, so the message has to carry the text itself or the failure
    is unreproducible.
    """
    cli = DogwoodCli(
        binary=dogwood_binary,
        policy=POLICY_DIR / "pay.dw",
        schemas=("--policy-schema", str(POLICY_DIR / SCHEMA_FILE)),
    )

    # A line with no leading `@`. The engine answers "timepoint must start with
    # `@`" and quotes nothing of the line, so this token can only reach the
    # caller if the message carries the events itself. Matching on a token the
    # engine echoes back would pass even with the trace text removed.
    with pytest.raises(EngineUnavailableError, match="UNECHOED-TRACE-TOKEN") as failure:
        cli.replay(("UNECHOED-TRACE-TOKEN scope() no leading at sign",))

    assert "dogwood replay` failed" in str(failure.value)
    # And the engine's own diagnostic, which arrives on stdout under
    # `--format json` while stderr stays empty. Without the stdout fallback the
    # reason for the failure is dropped and only the input survives.
    assert "timepoint must start with" in str(failure.value)


def test_a_carriage_return_inside_an_event_is_refused(dogwood_binary: Path) -> None:
    """The guard that catches nothing downstream, and matters most.

    A `\\r` cannot split a line, so it never reaches the count check. An interior
    one is read as ordinary whitespace and retypes the value beside it, which is
    how a payment stops being a number without anything looking wrong.
    """
    cli = DogwoodCli(
        binary=dogwood_binary,
        policy=POLICY_DIR / "pay.dw",
        schemas=("--policy-schema", str(POLICY_DIR / SCHEMA_FILE)),
    )

    with pytest.raises(EngineUnavailableError, match="not a single trace event"):
        cli.replay(("@1786910400 scope() request_context(input: { amount_cents: 50\r00 })",))


def test_the_engine_allows_a_payment_whose_amount_a_carriage_return_retyped(
    dogwood_binary: Path, tmp_path: Path
) -> None:
    """What the guard above is worth, measured rather than asserted.

    `amount_cents: 50\\r00` parses as a string, so both forbids fail to evaluate,
    and a skipped forbid is an absent one. The engine answers ALLOW, with a
    populated errors array, and exits 0. `_explain` would refuse that verdict,
    but only after the engine was asked a question nobody wrote.
    """
    world = (POLICY_DIR / WORLD_FILE).read_text(encoding="utf-8").strip()
    agent = 'Support::Agent::"support-bot"'
    payload = "input: { amount_cents: 50\r00 }"
    trace = tmp_path / "trace.log"
    trace.write_text(
        f'@1786910400 scope(principal: {agent}, resource: Support::Order::"{ORDER}") '
        f'{world} request_context({payload}) Support::Action::"Pay"::request({payload})\n',
        encoding="utf-8",
    )

    done = subprocess.run(  # noqa: S603 (path comes from the fixture, not from input)
        [
            str(dogwood_binary),
            "replay",
            str(POLICY_DIR / "pay.dw"),
            "--policy-schema",
            str(POLICY_DIR / SCHEMA_FILE),
            "--trace",
            str(trace),
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    verdict = json.loads(done.stdout)["verdicts"][0]
    assert verdict["verdict"] == "allow", "the guard would be pointless otherwise"
    assert verdict["errors"], "allowed with both forbids skipped"


def test_a_blank_event_is_refused_by_name(dogwood_binary: Path) -> None:
    """The count check would catch this too, but not by name.

    A blank line contributes no verdict, so the totals disagree and the failure
    arrives as an arithmetic complaint about counts. Refusing it here means the
    message says what was actually wrong with the input.
    """
    cli = DogwoodCli(
        binary=dogwood_binary,
        policy=POLICY_DIR / "pay.dw",
        schemas=("--policy-schema", str(POLICY_DIR / SCHEMA_FILE)),
    )

    with pytest.raises(EngineUnavailableError, match="not a single trace event"):
        cli.replay(("   ",))
