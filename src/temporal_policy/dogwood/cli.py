"""The `dogwood` binary, as a typed Python interface.

Dogwood ships no Python binding, so the engine is a child process answering in
JSON. Two measured properties of the CLI shape this module: `replay` does not
validate, and it emits a verdict only for events it reads as decision points,
exiting 0 either way. A short answer therefore looks like success.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any

from cedarpy import policies_to_json_str

from temporal_policy.decision import EngineUnavailableError

ALLOW = "allow"
DENY = "deny"


@dataclass(frozen=True)
class Verdict:
    """One decision event's outcome.

    ``determining_rules`` holds positions into the policy file's rule order,
    counting rules with no ``@id``, so naming one is a separate job.
    """

    verdict: str
    determining_rules: tuple[int, ...]
    errors: tuple[str, ...]

    @property
    def allowed(self) -> bool:
        return self.verdict == ALLOW


class DogwoodCli:
    """Runs one Dogwood binary against one policy.

    Validated at construction, because `replay` does not validate and will
    serve confident verdicts from a policy the validator rejects.
    """

    def __init__(
        self,
        binary: Path,
        policy: Path,
        schemas: tuple[str, ...],
        timeout_seconds: float = 30.0,
    ) -> None:
        self._binary = binary
        self._timeout_seconds = timeout_seconds
        self._policy = policy
        # Held once so `validate` and `replay` cannot read the policy under
        # different schemas, which would change its meaning.
        self._schemas = schemas
        self._validate()

    def replay(self, events: tuple[str, ...]) -> tuple[Verdict, ...]:
        """Decide a whole trace, and return one verdict per event.

        A failure carries the events, because the engine's diagnostics cite a
        line number and at most the fragment that failed, and the trace file is
        gone by then.
        """
        for event in events:
            # One event must be one line. A blank event contributes no verdict,
            # so the count check catches it downstream; the carriage return is
            # the arm that earns this loop. A `\r` cannot split a line, so nothing downstream
            # sees it, but an interior one is read as whitespace and retypes the
            # value beside it: `amount_cents: 50\r00` becomes a string, both
            # forbids fail to evaluate, and the engine answers ALLOW, exit 0.
            if not event.strip() or "\n" in event or "\r" in event:
                message = f"not a single trace event: {event[:60]!r}"
                raise EngineUnavailableError(message)
        _require_forward_in_time(events)

        with tempfile.TemporaryDirectory() as workdir:
            trace = Path(workdir) / "trace.log"
            trace.write_text("".join(line + "\n" for line in events), encoding="utf-8")
            completed = self._run(
                [
                    "replay",
                    str(self._policy),
                    *self._schemas,
                    "--trace",
                    str(trace),
                    "--format",
                    "json",
                ]
            )

            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout).strip()
                message = (
                    f"`dogwood replay` failed ({completed.returncode}) on trace "
                    f"{events!r}: {detail}"
                )
                raise EngineUnavailableError(message)

        verdicts = parse_verdicts(completed.stdout)
        if len(verdicts) != len(events):
            # Every event either version writes is a `::request`, the only kind
            # either event schema marks as a decision, so one verdict per event
            # holds. An event of any other kind contributes none, with no error
            # and no warning, which would attribute one payment's verdict to
            # another.
            message = (
                f"`dogwood replay` returned {len(verdicts)} verdicts for {len(events)} events, "
                "so at least one was not read as a decision point"
            )
            raise EngineUnavailableError(message)
        return verdicts

    def declared_rule_ids(self) -> tuple[str, ...]:
        """Every rule's `@id`, in the order the policy file declares them.

        `lower` emits the set as Cedar in source order, so cedarpy can parse the
        ids rather than pattern-matching the source.
        """
        completed = self._run(
            ["lower", str(self._policy), *self._schemas, "--emit", "cedar-policies"]
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            message = f"`dogwood lower` failed ({completed.returncode}): {detail}"
            raise EngineUnavailableError(message)

        # stdout is Cedar and nothing else; `lower` writes advisory notes to
        # stderr, including for a temporal policy set.
        try:
            parsed = json.loads(policies_to_json_str(completed.stdout))
            static: dict[str, Any] = parsed["staticPolicies"]
            # Handles are `policy0`, `policy1`, ... and carry the source order.
            ordered = sorted(
                static.items(), key=lambda item: int(item[0].removeprefix("policy"))
            )
            return tuple(str(policy["annotations"]["id"]) for _, policy in ordered)
        except (TypeError, ValueError, KeyError) as failure:
            message = f"could not read the rule ids `dogwood lower` emitted: {failure}"
            raise EngineUnavailableError(message) from failure

    def _validate(self) -> None:
        completed = self._run(["validate", str(self._policy), *self._schemas])
        if completed.returncode != 0:
            detail = (completed.stdout + completed.stderr).strip()
            message = f"{self._policy} was rejected by `dogwood validate`: {detail}"
            raise EngineUnavailableError(message)

    def _run(self, arguments: list[str]) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(  # noqa: S603 (binary is located by the caller, not by input)
                [str(self._binary), *arguments],
                capture_output=True,
                text=True,
                check=False,
                # A hung engine must not hang the gate, which is a cost Cedar
                # does not have. A parameter so a test need not wait it out.
                timeout=self._timeout_seconds,
            )
        except OSError as failure:
            message = f"cannot run `{self._binary}`: {failure}"
            raise EngineUnavailableError(message) from failure
        except subprocess.TimeoutExpired as failure:
            message = f"`{self._binary}` did not answer within {self._timeout_seconds}s"
            raise EngineUnavailableError(message) from failure


def _timestamp_of(event: str) -> int:
    """The `@<epoch-seconds>` a trace line must open with."""
    stamp = event.split(maxsplit=1)[0]
    if not stamp.startswith("@") or not stamp[1:].lstrip("-").isdigit():
        message = f"not a Dogwood event line: {event[:60]!r}"
        raise EngineUnavailableError(message)
    return int(stamp[1:])


def _require_forward_in_time(events: tuple[str, ...]) -> None:
    """Refuse a trace Dogwood does not promise to read correctly.

    Events are replayed in file order and their timestamps are never checked
    against it. The unsafe direction is a payment stamped before one already in
    the trace: a window looks only backwards, so it sees none of the payments it
    should have joined. Measured, two payments of $60.00 an hour apart are
    allowed then denied, and both are allowed when the later is written first.

    Equal stamps are refused because the contract is strict increase, not
    because they were seen to misbehave; whole seconds are the finest stamp
    Dogwood takes, so a second payment inside one second is refused with them.

    A lone event is never parsed, which leaves a malformed line to the engine's
    own diagnostic, and that one names the line number.
    """
    for earlier, later in pairwise(events):
        if _timestamp_of(later) <= _timestamp_of(earlier):
            message = (
                f"trace timestamps do not move forward: {earlier[:40]!r} then {later[:40]!r}. "
                "Dogwood replays events in file order and cannot detect it."
            )
            raise EngineUnavailableError(message)


def _checked_verdict(value: object) -> str:
    """Exactly two verdicts exist, so anything else is a change of shape.

    Unchecked, an unknown string is silently not-an-allow, and would become an
    approval under a one character change to `Verdict.allowed`.
    """
    verdict = str(value)
    if verdict not in (ALLOW, DENY):
        message = f"`dogwood replay` returned an unknown verdict {verdict!r}"
        raise EngineUnavailableError(message)
    return verdict


def parse_verdicts(stdout: str) -> tuple[Verdict, ...]:
    """Turn the CLI's JSON into typed values, or refuse it.

    The output carries no version field, so a change of shape has to fail here
    rather than as a KeyError from inside a decision.
    """
    try:
        payload = json.loads(stdout)
        return tuple(
            Verdict(
                verdict=_checked_verdict(entry["verdict"]),
                determining_rules=tuple(int(index) for index in entry["determining_rules"]),
                errors=tuple(str(error) for error in entry["errors"]),
            )
            for entry in payload["verdicts"]
        )
    except (TypeError, ValueError, KeyError) as failure:
        message = f"could not read `dogwood replay` output: {failure}"
        raise EngineUnavailableError(message) from failure
