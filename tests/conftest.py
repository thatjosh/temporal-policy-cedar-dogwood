"""Shared fixtures.

There is one shared concern: finding the Dogwood engine. Cedar arrives through
the lockfile like any other library, so it needs no fixture at all. That
asymmetry is the point, and it is why this file only mentions one of the two
engines.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

# `make dogwood` builds the pinned revision to here. Checking it before PATH
# means the documented setup needs no `export`, and cannot silently pick up some
# other build that happens to be installed on the machine.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_BUILT_BY_MAKE = _REPO_ROOT / ".tools" / "bin" / "dogwood"

_FIXTURE = "dogwood_binary"
_MARKER = "dogwood"


def _candidates() -> list[tuple[str, Path | None]]:
    """Every place the engine may be, in the order we trust it, each labelled.

    Returned rather than collapsed to a single answer so a failure can say what
    it looked at. The advice "set DOGWOOD_BIN" is useless to the one person most
    likely to hit it: someone whose DOGWOOD_BIN is already set, and wrong.

    An explicit override wins so a developer with several builds can state which
    one the suite measured, instead of finding out afterwards. Paths are
    resolved, because a relative override stops meaning the same thing the
    moment a test changes directory, which the engine tests will do once they
    write trace files into temporary directories.
    """
    override = os.environ.get("DOGWOOD_BIN")
    on_path = shutil.which("dogwood")
    return [
        ("DOGWOOD_BIN", Path(override).resolve() if override else None),
        ("built by `make dogwood`", _BUILT_BY_MAKE),
        ("on PATH", Path(on_path).resolve() if on_path else None),
    ]


def _usable(path: Path | None) -> bool:
    """A path that exists but cannot be executed is the failure this guards.

    A stale override, or a copy that lost its executable bit, otherwise survives
    until the first ``subprocess`` call and surfaces as ``Permission denied``
    from somewhere deep in a test, which says nothing about how to fix it.
    """
    return path is not None and path.is_file() and os.access(path, os.X_OK)


def _explain_missing() -> str:
    tried = "\n".join(
        f"  {source:24} {path if path else '(not set)'}" for source, path in _candidates()
    )
    return f"""\
The Dogwood engine was not found, so its half of this suite cannot run.

It is not skipped, on purpose: a suite that reports success having never asked
the engine anything is worse than a red one.

Looked in, in order:

{tried}

Build it. This fetches the pinned revision into .tools/ and installs nothing
system-wide:

    make dogwood

To run only the half that needs no engine:

    make test-cedar
"""


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark every test that asks for the engine, so nobody has to remember to.

    The marker decides what ``make test-cedar`` and the Rust-free CI job run, so
    a forgotten one is not a cosmetic slip: the test gets collected on a runner
    that has no engine and never can have one, and the job fails with an install
    message it cannot act on. Deriving the marker from the fixture makes the two
    incapable of disagreeing.
    """
    for item in items:
        if isinstance(item, pytest.Function) and _FIXTURE in item.fixturenames:
            item.add_marker(_MARKER)


@pytest.fixture(scope="session")
def dogwood_binary() -> Path:
    """The Dogwood CLI, or a loud failure naming everywhere it was not.

    An unusable ``DOGWOOD_BIN`` stops the search rather than falling through to
    the next candidate. Falling through would answer a question nobody asked:
    someone who set the variable is telling us which engine to measure, and
    quietly measuring a different one is the precise failure this fixture is
    here to prevent. The suite would go green against a build its author did
    not choose and does not know about.
    """
    override, built, on_path = _candidates()

    if override[1] is not None:
        if not _usable(override[1]):
            pytest.fail(_explain_missing(), pytrace=False)
        return override[1]

    for _, path in (built, on_path):
        if _usable(path):
            assert path is not None  # narrowed by _usable
            return path
    pytest.fail(_explain_missing(), pytrace=False)
