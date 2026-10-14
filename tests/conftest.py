"""Shared test setup.

The schema tooling under ``tools/schema`` is importable from tests because it is
worth testing. It is not a package, and neither is ``tools``: ``gen.py`` works
when run directly because Python puts the script's own directory on the path,
which is a different mechanism. Without this shim, ``import schema.gen_adapters``
raises ``ModuleNotFoundError`` under pytest, and the temptation is to conclude the
tooling is untestable and delete the test that proved it. That happened once.

Kept here rather than in a per-test module so every test gets it.
"""

from __future__ import annotations

import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"

if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
