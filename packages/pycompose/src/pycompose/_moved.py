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
    new: str | tuple[str, ...],
    namespace: dict[str, Any],
    *,
    submodules: dict[str, str] | None = None,
) -> None:
    """Fill an old module with a moved module's public names, warning once.

    Args:
        old: The old module's name, usually ``__name__``.
        new: The module it moved to, or the modules it was split into.
        namespace: The old module's ``globals()``.
        submodules: Old submodule names mapped to the modules they became, so
            ``import old.sub`` keeps working too.
    """
    targets = (new,) if isinstance(new, str) else new
    warnings.warn(
        f"{old} moved to {' and '.join(targets)}; import it from there",
        DeprecationWarning,
        stacklevel=3,
    )
    names: list[str] = []
    for target in targets:
        module = importlib.import_module(target)
        public = [name for name in getattr(module, "__all__", ()) if name not in names]
        namespace.update({name: getattr(module, name) for name in public})
        names += public
    namespace["__all__"] = names
    for old_name, new_name in (submodules or {}).items():
        sys.modules[f"{old}.{old_name}"] = importlib.import_module(new_name)
