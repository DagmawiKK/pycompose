"""Setup every test session shares, whichever package's tests it runs.

Each distribution keeps its tests beside it (``packages/*/tests``) and the
repository's own -- the examples, the tools, CI -- live in ``tests/``. pytest
loads this file for all of them, so ``pytest packages/pycompose/tests`` runs one
package's tests alone with the same setup as the whole suite.

``tools/`` is repo-only, so the root goes on the path for it to resolve; pytest
does not put it there.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# The package's copied assets -- the Android template, the extraction module,
# the lock and wire schema -- are assembled from their sources, never committed;
# the session runs against copies made from what is checked out now.
from tools.template.sync import assemble  # noqa: E402

assemble()

# The notes example's component slice is build output, as it is for any app;
# the session builds it from the example's sources before anything reads it.
from pycompose_codegen.emit.main import build_app  # noqa: E402

if build_app(ROOT / "examples/notes/app") != 0:
    raise RuntimeError("the notes example's component slice could not be built")


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
