"""Prop and slot rules: the component-property validator family.

Validates prop dicts: types, defaults, nullability, providers, actions
and slots. Importing :mod:`.rules` for ``die`` and shared constants is fine;
``rules`` calls back into the validators here lazily.
"""

import math
from typing import Any

from pycompose.contract.registry_types import CONSUMERS, SLOT_KINDS
from pycompose_codegen.emit.rules import (
    DOTTED_NAME,
    NATIVE_PARAMETER,
    PROP_TYPE_VOCABULARY,
    RESERVED_SLOTS,
    SLOT_KEYS,
    SLOT_NAME,
    die,
)

PROVIDER_KEYS = frozenset({"native", "returns"})


def _validate_children(
    name: str, children: dict[str, Any], props: dict[str, Any]
) -> None:
    """Check a component's children declaration and the scope it provides.

    Args:
        name: Component name, for error messages.
        children: The component's raw ``children`` object.
        props: The component's props, one of which keyed children name.
    """
    if not isinstance(children.get("allowed"), bool):
        die(f"component {name!r} needs children.allowed as a boolean")
    if children.get("kind", "content") not in SLOT_KINDS:
        die(
            f"component {name!r} children.kind must be one of "
            + ", ".join(sorted(SLOT_KINDS))
        )
    key = props.get(children.get("key", ""), {})
    if (children.get("kind") == "keyed") != ("key" in children) or (
        "key" in children and (key.get("type"), key.get("required")) != ("string", True)
    ):
        die(f"component {name!r} keyed children need a 'key' naming a required string")
    if "min" in children and not isinstance(children["min"], int):
        die(f"component {name!r} children.min must be an integer")
    natively = children.get("native")
    if natively is not None and not (
        isinstance(natively, str) and NATIVE_PARAMETER.match(natively)
    ):
        die(f"component {name!r} children.native must be a parameter name")
    if children.get("consume") not in {None, *CONSUMERS}:
        die(
            f"component {name!r} children.consume must be one of "
            + ", ".join(sorted(CONSUMERS))
        )
    provides = children.get("provides")
    if provides is None:
        return
    if not _receiver_class(provides):
        die(f"component {name!r} children.provides must name a receiver class")
    if children.get("consume") is not None:
        die(f"component {name!r} children cannot consume and provide a scope")
    if children.get("kind", "content") not in {"content", "keyed"}:
        die(f"component {name!r} children.provides needs the content kind")


def _receiver_class(value: object) -> bool:
    """Whether a scope is spelled as the dotted receiver class adapters import."""
    return (
        isinstance(value, str)
        and "." in value
        and DOTTED_NAME.fullmatch(value) is not None
    )


def _validate_scope(name: str, comp: dict[str, Any]) -> None:
    """Check a component's declared receiver names a scope.

    A component the pin declares inside a composition scope cannot be looked up
    like a plain one: its receiver exists only inside the parent lambda that
    provides it, so the adapter registers as scoped to that receiver class.
    The fact itself is re-derived from the pinned inventory by the compiler.

    Args:
        name: Component name, for error messages.
        comp: The component's schema entry.
    """
    scope = comp.get("scope")
    if scope is None:
        return
    if not _receiver_class(scope):
        die(f"component {name!r} scope must name a receiver class")


def _validate_slots(
    name: str,
    props: dict[str, Any],
    children: dict[str, Any],
    slots: object,
) -> None:
    """Check a component's declared slots against the slot vocabulary.

    Args:
        name: Component name, for error messages.
        props: The component's props, which no slot may shadow.
        children: The component's ``children`` object, whose native parameter a
            slot must not reuse either.
        slots: The raw ``slots`` object.
    """
    if not isinstance(slots, dict):
        die(f"component {name!r} needs a 'slots' object")
    natives: set[str] = {children.get("native", "content")}
    for slot_name, slot in sorted(slots.items()):
        where = f"component {name!r} slot {slot_name!r}"
        _validate_slot(where, slot_name, slot, natives, props)


def _validate_host_slot(where: str, slot: dict[str, Any]) -> None:
    """Check a host slot declares no native policy at all.

    Args:
        where: Human-readable location, for error messages.
        slot: The raw slot object, already known to carry ``host``.
    """
    if slot != {"host": True}:
        die(f"{where}: a host slot declares only host=true")


def _validate_slot(
    where: str,
    slot_name: str,
    slot: object,
    natives: set[str],
    props: dict[str, Any],
) -> None:
    """Check one declared slot, claiming its native parameter in ``natives``.

    Args:
        where: Human-readable location, for error messages.
        slot_name: The declared ``camelCase`` name.
        slot: The raw slot object.
        natives: Native parameters the component already claims, including the
            primary children's.
        props: The component's props, which no argument name may repeat.
    """
    if not isinstance(slot_name, str) or not SLOT_NAME.match(slot_name):
        die(f"{where}: the name must be camelCase")
    if slot_name in RESERVED_SLOTS or slot_name in props:
        die(f"{where}: the name collides with a prop or reserved argument")
    if not isinstance(slot, dict):
        die(f"{where} must be an object")
    unknown = sorted(set(slot) - SLOT_KEYS)
    if unknown:
        die(f"{where} has unknown keys: {', '.join(unknown)}")
    if "host" in slot:
        _validate_host_slot(where, slot)
        return
    native = slot.get("native")
    if not isinstance(native, str) or not NATIVE_PARAMETER.match(native):
        die(f"{where}: 'native' must be a parameter name")
    if native in natives or native in props:
        # Two arguments with one name is not valid Kotlin, and a slot that
        # shadows a prop drops one of them silently.
        die(f"{where}: 'native' repeats another parameter")
    natives.add(native)
    if not isinstance(slot.get("nullable", False), bool):
        die(f"{where}: 'nullable' must be a boolean")
    if slot.get("kind", "content") not in set(SLOT_KINDS) - {"keyed"}:
        die(f"{where}: 'kind' must be content or items")
    if slot.get("consume") not in {None, *CONSUMERS}:
        die(f"{where}: 'consume' must be one of " + ", ".join(sorted(CONSUMERS)))
    if slot.get("nullable", False) and slot.get("consume") is not None:
        # A consumed scope has to be applied, which a null slot never is.
        die(f"{where}: 'consume' needs a non-nullable slot")
    if slot.get("nullable", False) and slot.get("kind") == "items":
        # A nullable parameter takes a plain lambda, which cannot list items
        # lazily; composing them eagerly instead would be a different tree.
        die(f"{where}: an items slot cannot be nullable")
    _validate_slot_provides(where, slot)


def _validate_slot_provides(where: str, slot: dict[str, Any]) -> None:
    """Check the optional receiver a named slot provides.

    Args:
        where: Human-readable location, for error messages.
        slot: The raw slot object.
    """
    provides = slot.get("provides")
    if provides is None:
        return
    if not _receiver_class(provides):
        die(f"{where}: 'provides' must name a receiver class")
    if slot.get("consume") is not None:
        # Consuming a scope and providing one would need two nested lambdas;
        # the renderer has no such shape.
        die(f"{where}: cannot consume and provide a scope")
    if slot.get("kind", "content") != "content":
        # Items are emitted as keyed eager calls, which cannot carry a
        # composable receiver.
        die(f"{where}: 'provides' needs the content kind")


def _validate_prop(
    name: str, prop_name: str, prop: dict[str, Any], *, held: bool = False
) -> None:
    if not isinstance(prop, dict):
        die(f"prop {name}.{prop_name} must be an object")
    ptype = prop.get("type")
    if ptype not in PROP_TYPE_VOCABULARY:
        die(
            f"prop {name}.{prop_name} has unknown type {ptype!r}; "
            f"vocabulary: {sorted(PROP_TYPE_VOCABULARY)}"
        )
    if ptype == "enum":
        values = prop.get("values")
        if (
            not isinstance(values, list)
            or not values
            or not all(isinstance(value, str) for value in values)
        ):
            die(f"enum prop {name}.{prop_name} needs a non-empty string 'values' list")
    if "required" in prop and not isinstance(prop["required"], bool):
        die(f"prop {name}.{prop_name} 'required' must be a boolean")
    for bound in ("minimum", "maximum"):
        if bound in prop and (
            not isinstance(prop[bound], int | float)
            or isinstance(prop[bound], bool)
            or (isinstance(prop[bound], float) and not math.isfinite(prop[bound]))
        ):
            die(f"prop {name}.{prop_name} {bound} must be finite numeric data")
    if "minimum" in prop and "maximum" in prop and prop["minimum"] > prop["maximum"]:
        die(f"prop {name}.{prop_name} minimum exceeds maximum")
    if "fallback" in prop:
        if prop.get("decode") is None and ptype != "color":
            die(f"prop {name}.{prop_name} 'fallback' needs a 'decode' or a colour")
        if not isinstance(prop["fallback"], str) or not prop["fallback"]:
            die(f"prop {name}.{prop_name} 'fallback' must be Kotlin source")
    _validate_defaults(name, prop_name, prop, ptype)
    if "provider" in prop:
        _validate_provider(name, prop_name, prop)
    _validate_nullable(name, prop_name, prop, held=held)


def _validate_defaults(
    name: str,
    prop_name: str,
    prop: dict[str, Any],
    ptype: object,
) -> None:
    """Check a prop's native default and the fallback a dp prop must declare.

    Args:
        name: Component name, for error messages.
        prop_name: Prop name, for error messages.
        prop: The prop's raw entry.
        ptype: The prop's declared type.
    """
    if "nativeDefault" in prop:
        if not isinstance(prop["nativeDefault"], str) or not prop["nativeDefault"]:
            die(f"prop {name}.{prop_name} 'nativeDefault' must be Kotlin source")
        if ptype not in {"value", "dp"}:
            # Anything else that carried one would never be read, and the
            # stated default would quietly differ from the pinned one.
            die(
                f"prop {name}.{prop_name} 'nativeDefault' is read only for "
                "value and dp props"
            )
    if ptype == "dp" and not (
        prop.get("required") or "default" in prop or "nativeDefault" in prop
    ):
        die(
            f"prop {name}.{prop_name} dp props must be required or carry a "
            "'default' or 'nativeDefault'"
        )


def _validate_nullable(
    name: str, prop_name: str, prop: dict[str, Any], *, held: bool
) -> None:
    """Check which of the two nullable shapes a prop may have.

    They are not the same shape. A *required* nullable prop has no omission: the
    pinned parameter takes no default, so the value is passed through as it
    stands, and that only lines up when the wire type *is* the native type -- an
    undecoded scalar, where ``None`` is a ``null``. An *optional* nullable prop
    is the ``OptionalValue`` form, where absence and an explicit null are two
    facts, and the generated adapter implements that for a value family
    (``Button.elevation``). A held scalar never reaches a native parameter: its
    holder reads the ``OptionalValue`` (``DatePicker.selectedDateMillis``). Every
    other combination would either be passed where it does not fit or dropped
    silently, so it is refused here.

    Args:
        name: Component name, for error messages.
        prop_name: The prop's schema name.
        prop: Its raw schema entry.
        held: Whether a state holder consumes it instead of the native call.
    """
    if not prop.get("nullable"):
        return
    from pycompose_codegen.emit.adapters.policy import SCALAR_KOTLIN

    if prop.get("required"):
        if prop["type"] not in SCALAR_KOTLIN or "decode" in prop:
            die(
                f"prop {name}.{prop_name}: a required nullable prop is passed "
                "through, so it must be an undecoded scalar"
            )
    elif prop["type"] != "value" and not (held and prop["type"] in SCALAR_KOTLIN):
        die(
            f"prop {name}.{prop_name}: an optional nullable prop needs the "
            "value family's absent/null distinction"
        )


def _validate_provider(name: str, prop_name: str, prop: dict[str, Any]) -> None:
    """Check a prop delivered through a zero-arg native lambda.

    A provider prop states a value the host reads during composition; the native
    parameter is a function the host supplies, never one the app can name. The
    prop stays required because an absent value would need a call-site branch
    between two overload shapes, which the plan rejects (ADR-0016 decision 22).
    ``returns`` is the pinned lambda's return type: the generator needs it to
    coerce the wire value, and composegen's check re-derives it from the pin.

    Args:
        name: Component name, for error messages.
        prop_name: The prop's schema name.
        prop: Its raw schema entry, whose ``provider`` object is validated.
    """
    provider = prop["provider"]
    unknown = sorted(set(provider) - PROVIDER_KEYS)
    if unknown:
        die(f"prop {name}.{prop_name} provider has unknown keys: " + ", ".join(unknown))
    if not prop.get("required"):
        die(f"prop {name}.{prop_name} provider 'native' needs the prop to be required")
    if prop.get("type") in {"modifier", "actionId"}:
        die(f"prop {name}.{prop_name} provider cannot wrap a {prop['type']} prop")


def _validate_action(action_id: str, action: dict[str, Any]) -> None:
    if not isinstance(action, dict):
        die(f"action {action_id!r} must be an object")
    payload = action.get("payload", {})
    if not isinstance(payload, dict):
        die(f"action {action_id!r} 'payload' must be an object")
    for field_name, field in sorted(payload.items()):
        is_invalid = (
            not isinstance(field, dict) or field.get("type") not in PROP_TYPE_VOCABULARY
        )
        if is_invalid:
            die(
                f"action {action_id!r} payload field {field_name!r} has an invalid type"
            )
        _validate_prop(action_id, field_name, field)
