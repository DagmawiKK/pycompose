"""Shared test setup.

``pycompose/schema/codegen`` ships inside the package because an installed
``pycompose`` needs it (ADR-0014). The remaining schema tooling -- the classpath
dump reader, the AndroidX API scraper, the drift checker -- is repo-only: it
reads paths under ``android/`` that do not exist in a wheel, and nothing an app
builds calls it.

That means those tests need the repo root on the path so ``tools.schema``
resolves, and pytest does not put it there. The shim used to be deleted along
with a failing test rather than diagnosed; it is here now, and the reason is
written down.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session")
def native_document():
    """Extract pinned artifacts once for tests at the native evidence boundaries."""
    if os.environ.get("PYCOMPOSE_NATIVE_API_TESTS") != "1":
        pytest.skip("native CI runs the pinned artifact extraction")
    result = subprocess.run(
        ["./gradlew", "dumpComposeDefaults", "--rerun-tasks", "--console=plain"],
        cwd="android",
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(Path("android/build/compose-api/inventory.json").read_text())


@pytest.fixture(autouse=True)
def verify_every_reuse(monkeypatch: pytest.MonkeyPatch) -> None:
    """Re-expand and compare every reused composable in every test session.

    Debug builds sample one reuse in eight to stay fast; a test has no such
    budget, so a composable reading something outside its arguments fails here
    on its first reuse rather than by chance.

    Args:
        monkeypatch: Restores the sampling rate after each test.
    """
    from pycompose.bridge import api

    monkeypatch.setattr(api, "VERIFY_EVERY", 1)
