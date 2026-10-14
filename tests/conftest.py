"""Shared test setup.

The schema codegen now lives inside the package as
``pycompose.schema.codegen``, so tests import it the ordinary way and need no
``sys.path`` help. It used to live in ``tools/schema``, where pytest could not
reach it without a shim -- which once ended with a passing test file deleted
rather than diagnosed. Keeping it importable is the fix.
"""

from __future__ import annotations
