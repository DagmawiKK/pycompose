"""The ``Literal`` alias each enumerated prop is annotated with."""

from __future__ import annotations

from typing import Any


def enum_aliases(registry: dict[str, Any]) -> dict[tuple[str, str], str]:
    """Name each enum prop's ``Literal`` alias, by component and prop.

    A prop taking its family's whole scale shares the family's alias
    (``_AlignmentHorizontal``); one narrowed by policy gets its own.

    Args:
        registry: The catalog lock.

    Returns:
        The alias of every enum prop.
    """
    scales: dict[str, tuple[str, ...]] = {}
    for spec in registry.get("valueTypes", {}).values():
        names = (spec.get("parameters") or {}).get("name", {}).get("values")
        if spec.get("kind") == "constant" and names:
            scales[spec["family"]] = tuple(n[:1].lower() + n[1:] for n in names)
    aliases: dict[tuple[str, str], str] = {}
    for component, spec in registry["components"].items():
        for field, prop in spec["props"].items():
            if prop["type"] != "enum":
                continue
            family = prop.get("valueType")
            whole = family is not None and tuple(prop["values"]) == scales.get(family)
            own = f"_{component}{field[:1].upper() + field[1:]}"
            aliases[(component, field)] = f"_{family}" if whole else own
    return aliases
