"""``python -m pycompose.codegen``.

Exists so the codegen has a runnable entry point inside an installed wheel, where
``tools/schema/gen.py`` is not present. ``python -m pycompose.codegen.main``
does the same thing and predates this file; this is the shorter name.
"""

from __future__ import annotations

from pycompose.codegen.main import main

if __name__ == "__main__":
    raise SystemExit(main())
