"""Both engines answer, and the Dogwood one is the build we think it is.

These sit under everything else in the suite. Every other test asks an engine a
question and believes the answer, which is only worth doing if the engine is
reachable and is the version the results were recorded against. When one of
these two fails, no other failure in the suite means anything.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from cedarpy import is_authorized

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
