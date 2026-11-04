"""Animation converters: the pin says which types Compose can animate.

``animateValueAsState`` takes a ``TwoWayConverter``, so a type is animatable
exactly when the pin declares a public property returning one for it. That is
the whole fact -- no list of types is kept here, and a type the pin gives no
converter is refused with that reason rather than hidden.

Every prop the lock carries is annotated with the Kotlin type the host would
animate it as, when the pin has a converter for it; ``animatable`` in the
runtime then reads that annotation instead of guessing from the wire type.
"""

from __future__ import annotations

from typing import Any, cast

from pycompose_codegen.derive.classpath_types import (
    Declaration,
    Inventory,
    KotlinType,
)
from pycompose_codegen.emit.adapters.eligibility import held_props
from pycompose_codegen.emit.rules import die

TWO_WAY = "androidx/compose/animation/core/TwoWayConverter"
FUNCTION = "kotlin/Function1"
COLOR_SPACE = "androidx/compose/ui/graphics/colorspace/ColorSpace"

WIRE_TYPES = {
    "dp": "androidx.compose.ui.unit.Dp",
    "color": "androidx.compose.ui.graphics.Color",
}
"""The wire types that name their own Kotlin type: ``dp`` is ``Dp``, nothing else.

``number`` and ``integer`` name no Kotlin type -- a number may be a Float, a
Double or a count of items -- so they need the lock to say more.
"""

NATIVE_TYPES = {
    "Int": "kotlin.Int",
    "Float": "kotlin.Float",
}
"""A prop whose wire type is wider than its parameter names the parameter."""


def animated_type(declaration: Declaration) -> str | None:
    """The Kotlin type this declaration's converter animates, if it is one.

    A converter property returns ``TwoWayConverter<T, V>`` for one concrete
    ``T``. ``Color.VectorConverter`` is the one that first takes a colour space
    and returns the converter; its ``T`` sits one argument deeper.

    Args:
        declaration: A pinned declaration.

    Returns:
        ``T`` as a dotted name, or None when the declaration is no converter or
        animates a type parameter rather than a type.
    """
    returns = declaration.return_type
    if returns.classifier == TWO_WAY:
        return _animated(returns)
    if returns.classifier != FUNCTION:
        return None
    arguments = returns.arguments
    if len(arguments) != 2:
        return None
    space, inner = (argument for _, argument in arguments)
    if space is None or space.classifier != COLOR_SPACE or inner is None:
        return None
    return _animated(inner)


def _animated(converter: KotlinType) -> str | None:
    """The first type argument, unless it is a type parameter."""
    if not converter.arguments:
        return None
    first = converter.arguments[0][1]
    if first is None or first.classifier.startswith("#"):
        return None
    return first.classifier.replace("/", ".")


def converters(found: Inventory) -> dict[str, dict[str, Any]]:
    """Every animation converter the pin declares publicly, by animated type.

    Args:
        found: The pinned inventory.

    Returns:
        Per animated Kotlin type, the expression that names its converter and
        the imports that expression needs.
    """
    table: dict[str, dict[str, Any]] = {}
    space = _space(found)
    for declaration in found.declarations:
        if declaration.document.get("visibility") != "PUBLIC":
            continue
        if declaration.document.get("declarationKind") != "property":
            continue
        animated = animated_type(declaration)
        if animated is not None and animated not in table:
            table[animated] = _entry(declaration, space)
    return dict(sorted(table.items()))


def _space(found: Inventory) -> tuple[str, str]:
    """The sRGB space constant the colour converter takes, and its import.

    Args:
        found: The pinned inventory.

    Returns:
        The constant's Kotlin expression and the import it needs.
    """
    spaces = _descendants(found, COLOR_SPACE)
    for declaration in found.declarations:
        if declaration.name != "Srgb":
            continue
        if declaration.document.get("visibility") != "PUBLIC":
            continue
        if declaration.return_type.classifier.replace("/", ".") not in spaces:
            continue
        owner = declaration.owner.rsplit(".", 1)[-1]
        return f"{owner}.{declaration.name}", f"{declaration.package}.{owner}"
    die("the pin declares no public sRGB ColorSpace constant for the colour converter")


def _descendants(found: Inventory, base: str) -> set[str]:
    """Every pinned class that is, or descends from, ``base``.

    A Kotlin property may narrow its declared type: the sRGB constant is typed
    ``Rgb``, not ``ColorSpace``, so identity alone would miss it.

    Args:
        found: The pinned inventory.
        base: The supertype, as a slash-separated classifier.

    Returns:
        The classifiers assignable to ``base``.
    """
    parents = {item.classifier: item.supertypes for item in found.classes}
    found_types = {base}
    pending = [base]
    while pending:
        current = pending.pop()
        for child, supertypes in parents.items():
            if current in supertypes and child not in found_types:
                found_types.add(child)
                pending.append(child)
    return found_types


def _entry(declaration: Declaration, space: tuple[str, str]) -> dict[str, Any]:
    """How generated Kotlin names this converter, and what it must import.

    Args:
        declaration: The converter's pinned declaration.
        space: The sRGB constant's expression and import.

    Returns:
        The expression and the imports it needs.
    """
    returns = declaration.return_type
    if returns.classifier == FUNCTION:
        # Color.VectorConverter(ColorSpace.Srgb) is a function of the space; it
        # shares its name with the core properties, so it is imported aliased.
        owner = _owner(declaration)
        constant, space_import = space
        return {
            "expression": f"{owner}.colorVectorConverter({constant})",
            "imports": [
                *_receiver_imports(declaration),
                f"{declaration.package}.{declaration.name} as colorVectorConverter",
                space_import,
            ],
        }
    if declaration.receiver is not None:
        return {
            "expression": f"{_owner(declaration)}.{declaration.name}",
            "imports": [
                *_receiver_imports(declaration),
                f"{declaration.package}.{declaration.name}",
            ],
        }
    return {
        "expression": declaration.name,
        "imports": [f"{declaration.package}.{declaration.name}"],
    }


def _receiver_imports(declaration: Declaration) -> list[str]:
    """The import that makes the receiver's simple name resolve, when it needs one."""
    assert declaration.receiver is not None
    classifier = declaration.receiver.classifier.replace("/", ".")
    classifier = classifier.removesuffix(".Companion")
    return [] if classifier.startswith("kotlin.") else [classifier]


def _owner(declaration: Declaration) -> str:
    """The receiver's simple name: ``Dp.Companion`` is used as ``Dp``."""
    assert declaration.receiver is not None
    classifier = declaration.receiver.classifier.replace("/", ".")
    classifier = classifier.removesuffix(".Companion")
    return classifier.rsplit(".", 1)[-1]


def annotate(lock: dict[str, Any]) -> None:
    """Record on every prop what a binding needs: its Kotlin type and its phase.

    Two gates decide whether it is offered at all. Capability: the pin must
    declare a converter for the prop's type. Authority: Python must be the sole
    author of the value; a prop a state holder fills is the user's, and
    reconciling the two is a later protocol, so it is left unannotated rather
    than offered.

    Args:
        lock: The assembled lock; its props gain ``animation`` and ``phase``.
    """
    table = lock["converters"]
    families = lock["valueTypes"]
    for entry in lock.get("components", {}).values():
        held = held_props(entry)
        for prop, spec in entry.get("props", {}).items():
            if prop not in held:
                _mark(prop, spec, entry, families, table)
    for entry in lock.get("modifiers", {}).values():
        for prop, spec in entry.get("props", {}).items():
            _mark(prop, spec, entry, families, table)


def _mark(
    prop: str,
    spec: dict[str, Any],
    entry: dict[str, Any],
    families: dict[str, Any],
    table: dict[str, Any],
) -> None:
    """Annotate one prop when the pin can animate its type.

    Args:
        prop: The prop's name in the entry.
        spec: The prop's lock entry, annotated in place.
        entry: The component or modifier carrying it.
        families: The lock's value families.
        table: The pin's converters, by animated Kotlin type.
    """
    call = entry.get("call") or {}
    kotlin = kotlin_type(prop, spec, entry, families)
    if kotlin in table:
        spec["animation"] = kotlin
        # The call states where its arguments are read; a prop read in
        # composition is the default, and every other phase must say so. A
        # provider is read when the component asks for it, while it draws.
        spec["phase"] = (
            "draw" if "provider" in spec else call.get("phase", "composition")
        )


def kotlin_type(
    prop: str,
    spec: dict[str, Any],
    entry: dict[str, Any],
    families: dict[str, Any],
) -> str | None:
    """The Kotlin type one prop's value carries, when the lock states it.

    A wire type is not a Kotlin type: an ``integer`` may mean an index, a
    timestamp or a selection range. So the lock states the type where it knows
    it -- the resolved call's argument, an approved value family, a narrowed
    native type, or a provider's return -- and a prop whose type it never states
    is left unannotated rather than guessed at.

    Args:
        prop: The prop's name in the entry.
        spec: The prop's lock entry.
        entry: The component or modifier carrying it.
        families: The lock's value families.

    Returns:
        A dotted Kotlin type, or None when the lock states none.
    """
    argument = (entry.get("call") or {}).get("arguments", {}).get(prop)
    if argument is not None and argument.get("type"):
        return cast("str", argument["type"])
    return stated_type(spec, families)


def stated_type(spec: dict[str, Any], families: dict[str, Any]) -> str | None:
    """The Kotlin type the lock states for a prop's value, when it states one.

    Args:
        spec: The prop's lock entry.
        families: The lock's value families.

    Returns:
        A dotted Kotlin type, or None when the wire type names none.
    """
    family = spec.get("valueType")
    if family is not None:
        return cast("str | None", families.get(family, {}).get("kotlinType"))
    provider = spec.get("provider") or {}
    native = spec.get("nativeType") or provider.get("returns")
    if native is not None:
        return NATIVE_TYPES.get(native)
    return WIRE_TYPES.get(spec["type"])
