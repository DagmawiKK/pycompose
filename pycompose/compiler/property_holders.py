"""State holders whose family the pin implies: a factory and mutable properties.

``TimePicker(state: TimePickerState)`` reads its holder's ``hour`` and ``minute``
and writes them as the user picks; Python wants to set them and hear them back.
That is the whole family whenever a holder has a public ``remember...`` factory
callable with no arguments, and every public scalar property it exposes can be
set: each property becomes a desired prop and an ``on<Property>Change`` report,
reconciled by the host's generic ``reconcileProperty``. A holder with a scalar
property it only reads (``DateRangePickerState.selectedStartDateMillis``) needs
a drive the pin does not name, so it is not one; its components stay refused.
"""

from __future__ import annotations

from typing import Any

from pycompose.compiler.classpath_dump import Inventory
from pycompose.compiler.classpath_types import Declaration

WIRE = {
    "kotlin/Boolean": ("boolean", "Boolean"),
    "kotlin/Int": ("integer", "Int"),
    "kotlin/Long": ("integer", "Long"),
    "kotlin/Float": ("number", "Float"),
    "kotlin/Double": ("number", "Double"),
    "kotlin/String": ("string", "String"),
}
"""Kotlin scalars a property may carry, as wire types and their native spelling."""


def _public(declaration: Declaration) -> bool:
    return (
        declaration.document.get("visibility") == "PUBLIC"
        and "kotlin/Deprecated" not in declaration.annotations
    )


def _settable(declaration: Declaration) -> bool:
    setter: dict[str, Any] = (declaration.document.get("accessors") or {}).get(
        "setter"
    ) or {}
    return setter.get("visibility") == "PUBLIC" and setter.get("callable") is True


def _factory(found: Inventory, classifier: str) -> Declaration | None:
    """The one ``remember...`` composable returning the holder, called bare.

    Several overloads all defaulted resolve, as Kotlin resolves them, to the one
    that needs the fewest defaults; a tie is ambiguous and yields none.
    """
    factories = sorted(
        (
            d
            for d in found.declarations
            if d.composable
            and d.name.startswith("remember")
            and d.document.get("declarationKind") == "function"
            and _public(d)
            and d.receiver is None
            and d.dispatch_receiver is None
            and d.return_type.classifier == classifier
            and not d.return_type.nullable
            and all(p.has_default for p in d.parameters)
        ),
        key=lambda d: len(d.parameters),
    )
    if not factories or (
        len(factories) > 1
        and len(factories[0].parameters) == len(factories[1].parameters)
    ):
        return None
    return factories[0]


def property_holders(found: Inventory) -> dict[str, dict[str, Any]]:
    """Every holder class whose family the pin implies, by slash classifier.

    Args:
        found: The pinned inventory.

    Returns:
        Per holder: its class, its factory, and its properties' wire specs.
    """
    properties: dict[str, list[Declaration]] = {}
    for d in found.declarations:
        if (
            d.document.get("declarationKind") == "property"
            and _public(d)
            and d.return_type.classifier in WIRE
            and d.dispatch_receiver is not None
        ):
            properties.setdefault(d.dispatch_receiver.classifier, []).append(d)
    holders = {}
    for classifier, members in sorted(properties.items()):
        factory = _factory(found, classifier)
        if factory is None or not all(_settable(d) for d in members):
            continue
        holders[classifier] = {
            "holder": classifier.replace("/", "."),
            "factory": f"{factory.package}.{factory.name}",
            "properties": {
                d.name: {
                    "type": WIRE[d.return_type.classifier][0],
                    "nativeType": WIRE[d.return_type.classifier][1],
                    **({"nullable": True} if d.return_type.nullable else {}),
                }
                for d in sorted(members, key=lambda d: d.name)
            },
        }
    return holders
