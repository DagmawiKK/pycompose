"""Per-app and library codegen from ``schema/components.json``.

    python -m pycompose.schema.codegen            # the library's artifacts
    python -m pycompose.schema.codegen --app DIR  # only what DIR uses

This lives inside the package rather than in ``tools/`` because ADR-0014 needs
an installed ``pycompose`` to generate an app's component slice, and a wheel does
not ship ``tools/``. The ``tools/schema`` scripts that need the network --
``compose_api.py``, ``propose.py``, ``check_upstream.py`` -- stay outside, since
nothing an app builds calls them.

Importing this package is not part of running an app. It is build-time code that
happens to ship in the same distribution.
"""

from __future__ import annotations

from pycompose.schema.codegen.main import build_app, main

__all__ = ["build_app", "main"]
