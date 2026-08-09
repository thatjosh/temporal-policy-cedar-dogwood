"""Both engines answer, and the Dogwood one is the build we think it is.

These sit under everything else in the suite. Every other test asks an engine a
question and believes the answer, which is only worth doing if the engine is
reachable and is the version the results were recorded against. When one of
these two fails, no other failure in the suite means anything.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, timedelta, timezone
from pathlib import Path

import pytest
from cedarpy import is_authorized

from temporal_policy.clock import require_utc
from temporal_policy.spec import BASE
from tests.conftest import engine_candidates, select_engine

# The version this repo's documented results were produced against. Dogwood is
# built from a pinned revision, so a mismatch means the pin moved without the
# documentation following it.
EXPECTED_DOGWOOD_VERSION = "1.0.0"


def test_cedar_reaches_a_verdict() -> None:
    """Cedar is a library, so 'reachable' means the import and a real decision."""
    request = {
        "principal": 'Agent::"support-bot"',
        "action": 'Action::"pay"',
        "resource": 'Order::"ORD-1"',
        "context": {},
    }
    allow_everything = "permit(principal, action, resource);"

    result = is_authorized(request, allow_everything, "[]")

    assert result.allowed
    assert not result.diagnostics.errors


def test_dogwood_reports_the_pinned_version(dogwood_binary: Path) -> None:
    """Dogwood is a binary, so 'reachable' means it runs and identifies itself.

    Asserting the version, not merely a zero exit: the engine is fetched and
    compiled by the repo, and a build that silently became a different version
    would invalidate every measurement recorded against it.
    """
    done = subprocess.run(  # noqa: S603 (path comes from the fixture, not from input)
        [str(dogwood_binary), "--version"],
        capture_output=True,
        text=True,
        check=True,
    )

    # Split rather than substring: "1.0.0" is in "dogwood 11.0.0" and in
    # "dogwood 1.0.0-rc1", so the check this test is named for would pass for a
    # major version bump and for a pre-release.
    assert done.stdout.split() == ["dogwood", EXPECTED_DOGWOOD_VERSION], done.stdout


def test_an_empty_dogwood_bin_is_an_override_not_an_absence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`DOGWOOD_BIN=""` is someone pointing at a build, badly.

    It arises whenever an unset shell variable is expanded. Treating it as unset
    resumes the search and measures whichever engine turns up, which is the
    failure the lookup order exists to prevent, and it is the one line of that
    logic nothing else covers.
    """
    monkeypatch.setenv("DOGWOOD_BIN", "")

    source, path = engine_candidates()[0]

    assert source == "DOGWOOD_BIN"
    assert path is not None, "an empty override must not read as absent"


def test_asking_for_the_engine_applies_the_marker(
    dogwood_binary: Path, request: pytest.FixtureRequest
) -> None:
    """The marker is derived from this fixture, and nothing proved it.

    It decides what `make test-cedar` and the Rust-free CI job collect, so if
    the derivation broke, the whole suite would stay green here and that job
    would fail with an install message it cannot act on.
    """
    assert request.node.get_closest_marker("dogwood") is not None


def test_an_unusable_override_stops_the_search(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A bad `DOGWOOD_BIN` must not fall through to some other build.

    Falling through answers a question nobody asked: someone who set the
    variable is saying which engine to measure, and quietly measuring a
    different one is the failure the lookup order exists to prevent.
    """
    monkeypatch.setenv("DOGWOOD_BIN", str(tmp_path / "not-a-build"))

    source, path = engine_candidates()[0]

    assert source == "DOGWOOD_BIN"
    assert path is not None
    assert not path.is_file(), "the override is unusable, and must still be the answer"


def test_a_relative_override_is_resolved(monkeypatch: pytest.MonkeyPatch) -> None:
    """A relative override stops meaning the same thing once a test chdirs.

    The engine tests write trace files in temporary directories, so this is not
    hypothetical.
    """
    monkeypatch.setenv("DOGWOOD_BIN", "./some/relative/dogwood")

    _, path = engine_candidates()[0]

    assert path is not None
    assert path.is_absolute()


def test_an_unusable_override_is_not_replaced_by_a_working_build(tmp_path: Path) -> None:
    """The override wins even when it is wrong, so nothing is measured silently.

    A usable fallback is offered alongside a broken override; the broken one
    must still decide the outcome.
    """
    working = tmp_path / "dogwood"
    working.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    working.chmod(0o755)
    candidates = [
        ("DOGWOOD_BIN", tmp_path / "not-a-build"),
        ("built by `make dogwood`", working),
        ("on PATH", None),
    ]

    with pytest.raises(LookupError) as missing:
        select_engine(candidates)

    # The list it was handed, not the one it could recompute from the
    # environment. Matching only the header would pass either way, which is how
    # this went unnoticed once already.
    reported = str(missing.value)
    assert "DOGWOOD_BIN" in reported
    assert str(tmp_path / "not-a-build") in reported
    assert str(working) in reported


def test_a_path_that_cannot_be_executed_is_not_an_engine(tmp_path: Path) -> None:
    """A file that exists but has lost its executable bit is not a build.

    Otherwise it survives to the first subprocess call and surfaces as
    `Permission denied` from inside a test, which says nothing about the cause.
    """
    unrunnable = tmp_path / "dogwood"
    unrunnable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    unrunnable.chmod(0o644)

    with pytest.raises(LookupError):
        select_engine([("DOGWOOD_BIN", unrunnable), ("on PATH", None)])


def test_a_build_made_by_make_wins_over_one_on_the_path(tmp_path: Path) -> None:
    """The documented precedence, which the README repeats.

    Checking `.tools/` before `PATH` is what lets the documented setup work with
    no `export`, and stops the suite silently measuring whatever other build
    happens to be installed on the machine.
    """
    built = tmp_path / "built"
    on_path = tmp_path / "on-path"
    for binary in (built, on_path):
        binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        binary.chmod(0o755)

    chosen = select_engine(
        [("DOGWOOD_BIN", None), ("built by `make dogwood`", built), ("on PATH", on_path)]
    )

    assert chosen == built


def test_an_instant_in_another_offset_is_normalised_to_utc() -> None:
    """Inert in v1, and the window itself in v2.

    Two names for the same instant must reach the engine as the same instant, or
    a rolling window means different things depending on who called.
    """
    elsewhere = BASE.astimezone(timezone(timedelta(hours=5)))

    assert require_utc(elsewhere).tzinfo is UTC
    assert require_utc(elsewhere) == require_utc(BASE)


def test_the_lookup_order_is_override_then_built_then_path() -> None:
    """The order itself, which `select_engine` takes on trust from its caller.

    `.tools/` before `PATH` is what lets the documented setup work with no
    `export`; the override before both is what lets someone say which build the
    suite measured. Reordering these is silent otherwise, because every entry is
    a usable candidate on somebody's machine.
    """
    assert [source for source, _ in engine_candidates()] == [
        "DOGWOOD_BIN",
        "built by `make dogwood`",
        "on PATH",
    ]
