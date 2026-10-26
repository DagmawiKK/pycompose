"""Every module and script a CI workflow runs still exists in the tree.

A refactor that moves a module passes every local check and fails only on
push, where the workflow names the old path; this catches it beforehand.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = sorted((ROOT / ".github/workflows").glob("*.yml"))

MODULE = re.compile(r"\bpython3? (?:-I )?-m ([A-Za-z_][\w.]*)")
SCRIPT = re.compile(r"\bpython3? (?:-I )?(?:- )?((?:tools|scripts)/[\w/.-]+\.py)")


def test_every_module_a_workflow_runs_is_importable() -> None:
    named = {m for path in WORKFLOWS for m in MODULE.findall(path.read_text())}
    missing = sorted(
        name
        for name in named
        if name.split(".")[0] in {"pycompose", "tools"}
        and importlib.util.find_spec(name) is None
    )
    assert not missing, f"workflows run modules that no longer exist: {missing}"


def test_every_script_a_workflow_runs_exists() -> None:
    named = {s for path in WORKFLOWS for s in SCRIPT.findall(path.read_text())}
    assert named, "the workflows run repository scripts; the pattern found none"
    missing = sorted(script for script in named if not (ROOT / script).is_file())
    assert not missing, f"workflows run scripts that no longer exist: {missing}"
