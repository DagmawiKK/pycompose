"""What a builder channel carries beyond its kind: a handed holder, applied scopes.

A slot lambda handed a holder records the property its members set and which
member sets each value; a builder of item components records the scopes whose
items it applies. Both are codegen facts the catalog validates on load.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from pycompose.errors import ComponentRegistryError


def handed(data: Mapping[str, object], where: str) -> Mapping[str, object] | None:
    """Read a channel's handed holder: its class, property and drives."""
    handed = data.get("handed")
    if handed is None:
        return None
    if not isinstance(handed, Mapping) or set(handed) != {"holder", "value", "drives"}:
        raise ComponentRegistryError(
            f"{where}: 'handed' carries exactly holder, value and drives"
        )
    return cast("Mapping[str, object]", handed)


def applies(data: Mapping[str, object], where: str) -> tuple[str, ...]:
    """Read the scopes a builder channel applies the item components of."""
    applies = data.get("applies", ())
    if not isinstance(applies, list | tuple) or not all(
        isinstance(scope, str) and scope for scope in applies
    ):
        raise ComponentRegistryError(f"{where}: 'applies' must list scopes")
    return tuple(applies)
