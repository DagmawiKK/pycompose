"""Entry point for the schema codegen; the implementation now lives in the package.

Kept as a script because ``Makefile``, CI and the pre-commit hooks all invoke
``python tools/schema/gen.py``. The code lives in the package, at
``packages/pycompose/src/pycompose/codegen/main.py``, because an installed
``pycompose`` has to be able to generate an app's component slice (ADR-0014),
and a wheel does not ship ``tools/``.

    python tools/schema/gen.py
    python tools/schema/gen.py --check
    python tools/schema/gen.py --app path/to/app
"""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):  # pragma: no cover - only when run as a script
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / "packages/pycompose/src"))

from pycompose.codegen.main import main

if __name__ == "__main__":
    raise SystemExit(main())
