"""A source folder git tracks nothing in is reported, unless git ignores it."""

from __future__ import annotations

import subprocess
from pathlib import Path

from tools.stale_packages import stale


def test_a_folder_left_holding_only_caches_is_stale(tmp_path: Path) -> None:
    source = tmp_path / "packages/lib/src/lib"
    (source / "kept").mkdir(parents=True)
    (source / "kept/__init__.py").write_text("")
    (source / "gone/__pycache__").mkdir(parents=True)
    (source / "gone/__pycache__/old.pyc").write_bytes(b"")
    (source / "assembled").mkdir()
    (tmp_path / ".gitignore").write_text("__pycache__/\nassembled/\n")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    assert stale(tmp_path) == [source / "gone"]
