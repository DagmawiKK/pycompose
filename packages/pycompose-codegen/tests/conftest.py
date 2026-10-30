"""Fixtures of the catalog pipeline's tests, mirroring ``derive/`` and ``emit/``.

Shared helpers (``families``, ``native_calls``) sit here; this directory is on
the path so a test in either folder imports them by name.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

ANDROID = HERE.parents[2] / "android"


@pytest.fixture(scope="session")
def native_document():
    """Extract pinned artifacts once for tests at the native evidence boundaries."""
    if os.environ.get("PYCOMPOSE_NATIVE_API_TESTS") != "1":
        pytest.skip("native CI runs the pinned artifact extraction")
    result = subprocess.run(
        ["./gradlew", "dumpComposeDefaults", "--rerun-tasks", "--console=plain"],
        cwd=ANDROID,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads((ANDROID / "build/compose-api/inventory.json").read_text())
