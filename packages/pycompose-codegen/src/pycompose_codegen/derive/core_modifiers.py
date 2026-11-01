"""The native calls behind the modifiers policy declares, found in the pin.

Policy states a modifier's wire contract -- ``padding`` takes ``value``, a dp
whose family is ``PaddingValues`` -- and the pin says which ``Modifier``
extension that contract calls. A block overload comes first, because a prop
read there invalidates one phase alone (:mod:`.core_blocks`); otherwise each
prop binds to a parameter of the overload that leaves the fewest defaults in
use (:mod:`.core_binding`). A tie is refused, never guessed.
"""

from __future__ import annotations

from typing import Any

from pycompose_codegen.derive.classpath_dump import Inventory
from pycompose_codegen.derive.core_binding import (
    bare,
    bind,
    candidates,
    defaults_used,
)
from pycompose_codegen.derive.core_blocks import deferred_call
from pycompose_codegen.derive.propose import identity


def _call(
    name: str, props: dict[str, Any], found: Inventory, families: dict[str, Any]
) -> dict[str, Any]:
    """The call one policy modifier makes."""
    deferred = deferred_call(name, props, found, families)
    if deferred is not None:
        return deferred
    overloads = candidates(found, name)
    bound = [
        (defaults_used(d, binding), d, binding)
        for d in overloads
        if (binding := bind(props, d, families)) is not None
    ]
    if not bound:
        raise ValueError(f"{name}: no overload in the pin takes these props")
    fewest = min(unused for unused, _, _ in bound)
    chosen = [(d, b) for unused, d, b in bound if unused == fewest]
    if len(chosen) > 1:
        raise ValueError(f"{name}: several overloads take these props equally")
    declaration, binding = chosen[0]
    call: dict[str, Any] = {
        "function": f"{declaration.package}.{declaration.name}",
        "source": identity(declaration),
        "arguments": binding,
        "phase": "composition",
    }
    riding = {
        prop: bare(name, prop, overloads)
        for prop, spec in props.items()
        if spec["type"] == "dp" and spec.get("valueType") not in (None, "Dp")
    }
    if riding:
        call["bare"] = riding
    return call


def core_modifiers(
    found: Inventory,
    modifiers: dict[str, dict[str, Any]],
    families: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Find the native call every policy modifier makes.

    Args:
        found: The pinned inventory.
        modifiers: The modifiers policy declares, by wire name.
        families: Approved value families, by family name.

    Returns:
        Each modifier with its ``call`` added, and each one that does not
        derive with why.
    """
    derived: dict[str, dict[str, Any]] = {}
    refused: dict[str, str] = {}
    for name, entry in sorted(modifiers.items()):
        try:
            derived[name] = {
                **entry,
                "call": _call(name, entry["props"], found, families),
            }
        except ValueError as exc:
            refused[name] = str(exc)
    return derived, refused
