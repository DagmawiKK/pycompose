"""Per-app and library codegen from ``schema/catalog.lock.json``.

    python -m pycompose.schema.codegen            # the library's artifacts
    python -m pycompose.schema.codegen --app DIR  # only what DIR uses

This lives inside the package rather than in ``tools/`` because ADR-0014 needs
an installed ``pycompose`` to generate an app's component slice, and a wheel does
not ship ``tools/``. The tools that read the pinned evidence --
``tools/schema`` and ``tools/composegen`` -- stay outside, since nothing an
app builds calls them.

Importing this package is not part of running an app. It is build-time code that
happens to ship in the same distribution.
"""

from __future__ import annotations

from pycompose.schema.codegen import main
from pycompose.schema.codegen.main import build_app
from pycompose.schema.codegen.main import main as run

# `main` stays the submodule and is not shadowed by a function of the same
# name: `from pycompose.schema.codegen import main` must give the module, or
# every caller reaching for a module-level constant gets a function instead.
# The entry point is therefore `run`.

__all__ = ["build_app", "main", "run"]
