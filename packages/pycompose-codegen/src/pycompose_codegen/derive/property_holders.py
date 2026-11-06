"""State holders whose family the pin implies: a factory and mutable properties.

``TimePicker(state: TimePickerState)`` reads its holder's ``hour`` and ``minute``
and writes them as the user picks; Python wants to set them and hear them back.
That is the family whenever a holder has a public ``remember...`` factory
callable with no arguments and a public scalar property it lets be set. Its
members sort by what the types say:

* a settable scalar property is a value: a desired prop and its report,
  reconciled by the host's generic ``reconcileProperty``;
* a read-only property the factory takes under its own name
  (``SliderState.steps``), and a factory parameter of a value family
  (``valueRange: ClosedFloatingPointRange``), fix the holder as it is created:
  each is a prop, and a different one re-creates the holder;
* any other read-only scalar (``isDragging``) is what the holder computes, and
  stays off the wire;
* a settable ``() -> Unit`` property (``onValueChangeFinished``) is when its
  values settle: one report named after it carries them all, rather than a
  report per change.

A read-only property the factory only seeds as ``initial...``
(``DateRangePickerState.selectedStartDateMillis``) is a value the pin gives no
drive, so its holder is not one; its components stay refused.
"""

from __future__ import annotations

from typing import Any

from pycompose_codegen.derive.classpath_dump import Inventory
from pycompose_codegen.derive.classpath_types import Declaration
from pycompose_codegen.derive.implementations import implementation_members
from pycompose_codegen.emit.defaults import render_default

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


def _seed(
    factory: Declaration, prop: Declaration, defaults: dict[str, Any]
) -> dict[str, Any] | None:
    """The factory parameter a property's holder is created at, if any.

    ``rememberTimePickerState(initialHour = 5)`` creates a holder whose dial
    stands at five; setting ``hour`` later moves the number but not the hand.
    A parameter named ``initial`` and the property's name, of its type, only
    seeds it, so the holder is re-created to drive it. A parameter named after
    the property itself (``rememberSliderState(value)``) is the same value the
    setter writes, so the setter drives it and it seeds nothing. Only a literal
    default is one the host can fall back on when the app states nothing, and
    only a non-null property can tell "states nothing" from "clears".
    """
    if prop.return_type.nullable:
        return None
    names = {"initial" + prop.name[:1].upper() + prop.name[1:]}
    for parameter in factory.parameters:
        default = defaults.get(parameter.name) or {}
        if (
            parameter.name in names
            and parameter.type.classifier == prop.return_type.classifier
            and default.get("kind") == "literal"
        ):
            return {"parameter": parameter.name, "default": default["value"]}
    return None


def _arguments(
    found: Inventory, factory: Declaration, defaults: dict[str, Any], seeded: set[str]
) -> dict[str, dict[str, Any]]:
    """Factory parameters that take functions the holder calls while it draws.

    ``rememberDatePickerState(selectableDates = ...)`` creates a holder that asks
    its ``SelectableDates`` about each day; the app gives one written as host
    functions. Only a parameter whose default names a property can be left to
    that default when the app gives none.
    """
    arguments = {}
    for parameter in factory.parameters:
        default = defaults.get(parameter.name) or {}
        if (
            parameter.name not in seeded
            and default.get("kind") == "property"
            and implementation_members(found, parameter.type.classifier) is not None
        ):
            arguments[parameter.name] = {
                "valueType": parameter.type.classifier.rsplit("/", 1)[-1],
                "default": default["symbol"],
            }
    return arguments


def property_holders(
    found: Inventory,
    defaults: dict[tuple[str, str, str], dict[str, Any]],
    families: dict[str, str],
) -> dict[str, dict[str, Any]]:
    """Every holder class whose family the pin implies, by slash classifier.

    Args:
        found: The pinned inventory.
        defaults: Compiler-resolved defaults by JVM identity, for the seeds.
        families: Value families by source-spelled native type.

    Returns:
        Per holder: its class, its factory, its properties' wire specs, what
        fixes it as it is created, and the member its values settle through.
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
    for classifier, every in sorted(properties.items()):
        factory = _factory(found, classifier)
        members = [d for d in every if _settable(d)]
        if factory is None or not members:
            continue
        parameters = {p.name: p for p in factory.parameters}
        fixed = [d for d in every if not _settable(d) and d.name in parameters]
        if any(_seeded(d) in parameters for d in every if not _settable(d)) or any(
            parameters[d.name].type.classifier != d.return_type.classifier
            for d in fixed
        ):
            continue
        own = defaults.get(
            (factory.owner, factory.jvm_name or "", factory.jvm_descriptor or ""), {}
        )
        held: dict[str, dict[str, Any]] = {
            d.name: {
                "type": WIRE[d.return_type.classifier][0],
                "nativeType": WIRE[d.return_type.classifier][1],
                **({"nullable": True} if d.return_type.nullable else {}),
                **({"seed": seed} if (seed := _seed(factory, d, own)) else {}),
            }
            for d in sorted(members, key=lambda d: d.name)
        }
        seeded = {spec["seed"]["parameter"] for spec in held.values() if "seed" in spec}
        arguments = _arguments(found, factory, own, seeded)
        construct = {
            **{
                d.name: _scalar(d.return_type.classifier, own.get(d.name))
                for d in fixed
            },
            **_families(factory, own, families, seeded | set(arguments)),
        }
        settles = [
            d.name
            for d in found.declarations
            if d.document.get("declarationKind") == "property"
            and d.dispatch_receiver is not None
            and d.dispatch_receiver.classifier == classifier
            and _public(d)
            and _settable(d)
            and d.return_type.classifier == "kotlin/Function0"
        ]
        holders[classifier] = {
            "holder": classifier.replace("/", "."),
            "factory": f"{factory.package}.{factory.name}",
            "properties": held,
            **({"arguments": arguments} if arguments else {}),
            **({"construct": construct} if construct else {}),
            **({"settles": settles[0]} if len(settles) == 1 else {}),
        }
    return holders


def _seeded(prop: Declaration) -> str:
    """The factory parameter that only seeds a property: ``initial`` and its name."""
    return "initial" + prop.name[:1].upper() + prop.name[1:]


def _scalar(classifier: str, default: dict[str, Any] | None) -> dict[str, Any]:
    """A scalar the holder is created with, defaulted where the pin states a literal."""
    wire, native = WIRE[classifier]
    literal = (default or {}).get("kind") == "literal"
    return {
        "type": wire,
        "nativeType": native,
        **(
            {"default": default["value"]} if literal and default else {"required": True}
        ),
    }


def _families(
    factory: Declaration,
    defaults: dict[str, Any],
    families: dict[str, str],
    taken: set[str],
) -> dict[str, dict[str, Any]]:
    """Factory parameters of a value family: ``valueRange`` as a ``Range``.

    A default the vocabulary renders stands when the app states none; any other
    makes the prop required, since the host cannot reproduce it.
    """
    found = {}
    for parameter in factory.parameters:
        family = families.get(parameter.type.classifier.replace("/", "."))
        if parameter.name in taken or family is None:
            continue
        default = defaults.get(parameter.name) or {}
        native: dict[str, object]
        try:
            native = {"nativeDefault": render_default(default, set())}
        except ValueError:
            native = {"required": True}
        found[parameter.name] = {"type": "value", "valueType": family, **native}
    return found
