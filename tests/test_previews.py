"""The committed render-gate samples are what the lock implies today."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_the_committed_samples_are_current() -> None:
    result = subprocess.run(
        [sys.executable, "tools/previews.py", "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
