"""Old module names that keep working for one release, pointing at the new.

A moved module's old name becomes a shim: importing it warns once with the new
name and hands over the same objects, so code written against the old name runs
unchanged while it migrates (ADR-0063). After that release each shim becomes an
error naming its replacement.
"""

from __future__ import annotations

import importlib
import sys
import warnings
from typing import Any

__all__ = ["forward"]


def forward(
    old: str,
    new: str,
    namespace: dict[str, Any],
    *,
    submodules: dict[str, str] | None = None,
) -> None:
    """Fill an old module with a moved module's public names, warning once.

    Args:
        old: The old module's name, usually ``__name__``.
        new: The module it moved to.
        namespace: The old module's ``globals()``.
        submodules: Old submodule names mapped to the modules they became, so
            ``import old.sub`` keeps working too.
    """
    warnings.warn(
        f"{old} moved to {new}; import it from there",
        DeprecationWarning,
        stacklevel=3,
    )
    module = importlib.import_module(new)
    names = list(getattr(module, "__all__", ()))
    namespace.update({name: getattr(module, name) for name in names})
    namespace["__all__"] = names
    for old_name, new_name in (submodules or {}).items():
        sys.modules[f"{old}.{old_name}"] = importlib.import_module(new_name)
