"""The runtime's tests, mirroring ``src/pycompose``.

The helpers every folder shares (``handlers``, ``readable``, ``images``,
``goldens``) sit here; this directory is on the path so a test in any folder
imports them by name.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = str(Path(__file__).resolve().parent)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
