"""Shared test setup.

The codegen and the component compiler ship inside the package, because an
installed ``pycompose`` runs them for an app (ADR-0014, ``pycompose add``). The
rest of ``tools/`` -- line budgets, the template sync, previews and the corpus
-- is repo-only.

That means those tests need the repo root on the path so ``tools`` resolves,
and pytest does not put it there. The shim used to be deleted along
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

# The package's copied assets -- the Android template, the extraction module,
# the lock and wire schema -- are assembled from their sources, never committed;
# the session runs against copies made from what is checked out now.
from tools.template.sync import assemble  # noqa: E402

assemble()

# The notes example's component slice is build output, as it is for any app;
# the session builds it from the example's sources before anything reads it.
from pycompose.codegen.main import build_app  # noqa: E402

if build_app(ROOT / "examples/notes/app") != 0:
    raise RuntimeError("the notes example's component slice could not be built")


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

    An app never pays for the check; a test has the budget, so a composable
    reading something outside its arguments fails here on its first reuse.

    Args:
        monkeypatch: Restores the sampling rate after each test.
    """
    from pycompose.bridge import api

    monkeypatch.setattr(api, "VERIFY_EVERY", 1)
