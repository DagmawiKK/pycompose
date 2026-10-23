"""The committed wire corpus is what Python's validator would write today."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_the_committed_corpus_is_current() -> None:
    result = subprocess.run(
        [sys.executable, "tools/corpus.py", "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
