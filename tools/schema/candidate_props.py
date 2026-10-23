"""Turn one planned native parameter into the wire shape the schema carries.

The planner classifies every parameter of one selected overload: modifier,
scalar, value family, action or composable slot. This module owns the second
half of that contract -- which wire prop (or slot, or children channel) a
policy becomes, and which default the pin supplies for it.

Every decision here is a refusal or a derivation, never a guess: a scalar needs
a literal default, an optional value prop needs a renderable one, a content
slot needs a renderer scope, and a long has no exact wire type. Review notes
record every place the wire shape differs from the native call.
"""

from __future__ import annotations

from typing import Any

from pycompose.core.registry_types import SCOPE_PATHS
from pycompose.schema.codegen.defaults import render_default
from tools.schema.component_face import DECODE_CLASSIFIERS
from tools.schema.propose_lookup import source_name

WIRE_SCALARS = {
    "int": "integer",
    "float": "number",
    "double": "number",
    "string": "string",
    "boolean": "boolean",
}
"""Plan scalar wire types the schema carries; a ``long`` has no exact one."""

PAYLOAD_NAMES = {
    "onCheckedChange": "value",
    "onExpandedChange": "expanded",
    "onOpenChange": "open",
    "onSelectionChange": "value",
    "onValueChange": "value",
}
"""Single-argument callbacks whose payload a semantic name makes legible."""

DECODE_TOKENS = {classifier: token for token, classifier in DECODE_CLASSIFIERS.items()}
"""Pinned classifier back to its wire decode token."""

SCOPE_NAMES = {path: scope for scope, path in SCOPE_PATHS.items()}
"""Pinned scope classifier back to its short approved name."""


def scope_for(classifier: str) -> str | None:
    """Return the closed scope name for a pinned receiver classifier.

    Args:
        classifier: A metadata classifier, slash-separated or source-spelled.

    Returns:
        The scope name, or None when the receiver is not a composition scope.
    """
    return SCOPE_NAMES.get(source_name(classifier))


class CandidateError(ValueError):
    """A plan, decision or registry state that cannot become a candidate."""


def family_index(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Index the approved value families by the name a plan records.

    Args:
        registry: The approved catalog.

    Returns:
        One family spec per approved family name.
    """
    return {
        spec["family"]: spec
        for spec in registry["valueTypes"].values()
        if spec.get("family")
    }


def wire_shape(
    name: str,
    plan: dict[str, Any],
    families: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], list[str]]:
    """Derive the props, children channel and slots of one call plan.

    Args:
        name: The component's schema name, for refusal messages.
        plan: A fresh call plan for exactly one pinned overload.
        families: The approved value families, from :func:`family_index`.

    Returns:
        The props, the children block, the named slots, and the review notes.

    Raises:
        CandidateError: A parameter asks for a shape the wire cannot carry.
    """
    if "modifier" not in plan["parameters"]:
        raise CandidateError(f"{name}: no modifier parameter; the wire carries one")
    props: dict[str, Any] = {}
    slots: dict[str, Any] = {}
    children: dict[str, Any] = {"allowed": False}
    review: list[str] = []
    for parameter, spec in plan["parameters"].items():
        policy = spec["policy"]
        if policy in {"modifier", "holder"}:
            # A holder is the component's state, not a prop; derive() binds it.
            continue
        if policy == "omit":
            reason = gap_reason(plan, parameter) or "no wire policy"
            review.append(f"{parameter}: omitted ({reason})")
            continue
        if policy == "slot":
            place_slot(name, parameter, spec, children, slots, review)
            continue
        prop = _prop(name, parameter, spec, families, review)
        if prop is not None:
            props[parameter] = prop
    props = dict(sorted(props.items()))
    props["modifier"] = {"type": "modifier"}
    return props, children, dict(sorted(slots.items())), review


def _prop(
    name: str,
    parameter: str,
    spec: dict[str, Any],
    families: dict[str, dict[str, Any]],
    review: list[str],
) -> dict[str, Any] | None:
    """Derive the wire prop one value-carrying policy becomes."""
    policy = spec["policy"]
    if policy == "scalar":
        return _scalar_prop(name, parameter, spec, review)
    if policy == "provider":
        return _provider_prop(name, parameter, spec, review)
    if policy == "resource":
        return _resource_prop(parameter, spec, review)
    if policy == "event":
        return _event_prop(name, parameter, spec, review)
    if policy == "value":
        family = families.get(spec["family"])
        if family is None:
            raise CandidateError(
                f"{name}.{parameter}: family {spec['family']!r} is not approved"
            )
        return _value_prop(name, parameter, spec, family, review)
    raise CandidateError(f"{name}.{parameter}: unknown policy {policy!r}")


def gap_reason(plan: dict[str, Any], parameter: str) -> str | None:
    """The planner's reason for leaving one parameter without a wire policy.

    Args:
        plan: The call plan the gap belongs to.
        parameter: The native parameter name.

    Returns:
        The reason the planner recorded, when it recorded one.
    """
    for gap in plan.get("gaps", ()):
        if gap.get("parameter") == parameter:
            reason = gap.get("reason")
            return reason if isinstance(reason, str) else None
    return None


def _camel(name: str) -> str:
    """Spell a Kotlin identifier the way the wire spells a prop."""
    return name[:1].lower() + name[1:]


def _literal_default(spec: dict[str, Any]) -> tuple[bool, Any]:
    """Return whether a parameter carries a literal default, and its value."""
    expression = spec.get("default")
    if expression is None or expression.get("kind") != "literal":
        return False, None
    return True, expression.get("value")


def _scalar_prop(
    name: str, parameter: str, spec: dict[str, Any], review: list[str]
) -> dict[str, Any] | None:
    """Derive a scalar prop, or drop an optional one the wire cannot default."""
    wire = WIRE_SCALARS.get(str(spec.get("wireType")))
    if wire is None:
        raise CandidateError(
            f"{name}.{parameter}: no wire type for {spec.get('wireType')!r}"
        )
    prop: dict[str, Any] = {"type": wire}
    if wire == "integer" and spec["type"].get("classifier") == "kotlin/Int":
        prop["nativeType"] = "Int"
        prop["minimum"] = -(2**31)
        prop["maximum"] = 2**31 - 1
    if spec["required"]:
        prop["required"] = True
        if spec["type"]["nullable"]:
            prop["nullable"] = True
        return prop
    if spec["type"]["nullable"]:
        review.append(
            f"{parameter}: omitted; an optional nullable scalar has no absent "
            "value on the wire"
        )
        return None
    has_default, value = _literal_default(spec)
    if not has_default or value is None:
        review.append(f"{parameter}: omitted; the default is not a literal")
        return None
    prop["default"] = value
    return prop


def _provider_prop(
    name: str, parameter: str, spec: dict[str, Any], review: list[str]
) -> dict[str, Any] | None:
    """Derive a late-read scalar: the host reads the wire value when called."""
    prop = _scalar_prop(name, parameter, spec, review)
    if prop is not None:
        returns = spec["type"]["arguments"][-1]["type"]["classifier"]
        prop["provider"] = {"native": parameter, "returns": returns.split("/")[-1]}
    return prop


def _resource_prop(
    parameter: str, spec: dict[str, Any], review: list[str]
) -> dict[str, Any] | None:
    """Derive a resource reference the host loads into the native type."""
    prop: dict[str, Any] = {
        "type": "resource",
        "values": spec["values"],
        "decode": spec["decode"],
    }
    if spec["required"]:
        prop["required"] = True
    elif _literal_default(spec) != (True, None):
        review.append(f"{parameter}: omitted; only an absent default is renderable")
        return None
    return prop


def _value_prop(
    name: str,
    parameter: str,
    spec: dict[str, Any],
    family: dict[str, Any],
    review: list[str],
) -> dict[str, Any] | None:
    """Derive a value-family prop through the approved encoding for it."""
    classifier = source_name(family["kotlinType"])
    token = DECODE_TOKENS.get(classifier)
    if spec["family"] == "Color":
        return _color_prop(name, parameter, spec, review)
    if spec["family"] == "Dp":
        return _dp_prop(parameter, spec, review)
    if token is not None and family.get("kind") == "constant":
        return _enum_prop(name, parameter, spec, family, token, review)
    return _plain_value_prop(name, parameter, spec, review)


def _render(
    parameter: str, spec: dict[str, Any], review: list[str]
) -> tuple[bool, str | None]:
    """Render the pinned default; an unrenderable one omits the parameter."""
    if "default" not in spec:
        return False, None
    try:
        return True, render_default(spec["default"], set())
    except ValueError as exc:
        review.append(f"{parameter}: omitted; default not renderable ({exc})")
        return True, None


def _color_prop(
    name: str, parameter: str, spec: dict[str, Any], review: list[str]
) -> dict[str, Any] | None:
    """Derive a theme color prop, whose absent value needs a fallback."""
    has_default, rendered = _render(parameter, spec, review)
    if has_default and rendered is None:
        return None
    required = bool(spec["required"])
    nullable = bool(spec["type"]["nullable"])
    if rendered is None:
        if required and not nullable:
            return {"type": "value", "valueType": "Color", "required": True}
        raise CandidateError(
            f"{name}.{parameter}: a color without a default has no fallback"
        )
    review.append(f"{parameter}: color with fallback {rendered}")
    return {
        "type": "color",
        "valueType": "Color",
        "decode": "color",
        "fallback": rendered,
    }


def _dp_prop(
    parameter: str, spec: dict[str, Any], review: list[str]
) -> dict[str, Any] | None:
    """Derive a raw dp prop, which cannot borrow a value-family resolver."""
    has_default, rendered = _render(parameter, spec, review)
    if has_default and rendered is None:
        return None
    prop: dict[str, Any] = {"type": "dp"}
    if spec["required"]:
        prop["required"] = True
    elif rendered is None:
        review.append(f"{parameter}: omitted; a dp prop needs a rendered default")
        return None
    if rendered is not None:
        prop["nativeDefault"] = rendered
    if spec["type"]["nullable"]:
        prop["nullable"] = True
    review.append(f"{parameter}: dp nativeDefault {rendered}")
    return prop


def _plain_value_prop(
    name: str, parameter: str, spec: dict[str, Any], review: list[str]
) -> dict[str, Any] | None:
    """Derive an ordinary value prop that carries its family reference."""
    has_default, rendered = _render(parameter, spec, review)
    if has_default and rendered is None:
        return None
    family = spec["family"]
    required = bool(spec["required"])
    nullable = bool(spec["type"]["nullable"])
    if required:
        if nullable:
            raise CandidateError(
                f"{name}.{parameter}: a required nullable value prop has no "
                "absent/null distinction"
            )
        return {"type": "value", "valueType": family, "required": True}
    if rendered is None:
        review.append(
            f"{parameter}: omitted; an optional value prop needs the family's "
            "default for its absent branch"
        )
        return None
    prop: dict[str, Any] = {
        "type": "value",
        "valueType": family,
        "nativeDefault": rendered,
    }
    if nullable:
        prop["nullable"] = True
    review.append(f"{parameter}: value nativeDefault {rendered}")
    return prop


def _enum_prop(
    name: str,
    parameter: str,
    spec: dict[str, Any],
    family: dict[str, Any],
    token: str,
    review: list[str],
) -> dict[str, Any] | None:
    """Derive a constant family as a decoded wire enum."""
    values = (family.get("parameters") or {}).get("name", {}).get("values")
    if not values:
        raise CandidateError(
            f"{name}.{parameter}: family {spec['family']!r} has no value names"
        )
    prop: dict[str, Any] = {
        "type": "enum",
        "values": [_camel(value) for value in values],
        "decode": token,
    }
    if spec["required"]:
        prop["required"] = True
        review.append(f"{parameter}: decoded {token} constant")
        return prop
    symbol = (spec.get("default") or {}).get("symbol")
    last = str(symbol).rsplit(".", 1)[-1] if symbol else ""
    if last not in values:
        review.append(
            f"{parameter}: omitted; default {symbol!r} is not a named constant"
        )
        return None
    prop["default"] = _camel(last)
    review.append(f"{parameter}: decoded {token} constant, default {_camel(last)}")
    return prop


def _event_prop(
    name: str, parameter: str, spec: dict[str, Any], review: list[str]
) -> dict[str, Any]:
    """Derive an actionId prop, naming a single-argument payload for its callback."""
    prop: dict[str, Any] = {"type": "actionId"}
    if spec["required"]:
        prop["required"] = True
    items = list(spec.get("payload") or ())
    renamed = PAYLOAD_NAMES.get(parameter) if len(items) == 1 else None
    payload = []
    for item in items:
        wire = WIRE_SCALARS.get(str(item.get("type")))
        if wire is None:
            raise CandidateError(
                f"{name}.{parameter}: payload type {item.get('type')!r} has no "
                "wire type"
            )
        field = renamed if renamed and item["name"] == "arg0" else item["name"]
        payload.append({"name": field, "type": wire})
    if payload:
        prop["payload"] = payload
        review.append(
            f"{parameter}: action payload kept {', '.join(p['name'] for p in payload)}"
        )
    return prop


def place_slot(
    name: str,
    parameter: str,
    spec: dict[str, Any],
    children: dict[str, Any],
    slots: dict[str, Any],
    review: list[str],
) -> None:
    """Route one composable parameter to children or a named slot.

    Args:
        name: The component's schema name, for refusal messages.
        parameter: The native parameter name.
        spec: The plan's parameter rule.
        children: The children block to update in place.
        slots: The named slots to update in place.
        review: Review notes to append to.

    Raises:
        CandidateError: The slot carries a scope the renderer cannot compose.
    """
    receiver = spec.get("receiver")
    nullable = bool(spec["type"]["nullable"])
    if receiver is not None:
        classifier = source_name(receiver)
        scope = scope_for(receiver)
        if scope is None:
            raise CandidateError(
                f"{name}.{parameter}: slot receiver {classifier} has no "
                "renderable scope"
            )
        if parameter == "content":
            children.update({"allowed": True, "kind": "content", "provides": scope})
            review.append(f"{parameter}: app content children in {scope}")
            return
        scoped: dict[str, Any] = {"native": parameter, "provides": scope}
        if nullable:
            scoped["nullable"] = True
            review.append(f"{parameter}: nullable named slot in {scope}")
        else:
            review.append(
                f"{parameter}: required native slot in {scope}; "
                "absence renders an empty lambda"
            )
        slots[parameter] = scoped
        return
    if parameter == "content":
        children["allowed"] = True
        review.append(f"{parameter}: app content children")
        return
    slot: dict[str, Any] = {"native": parameter}
    if nullable:
        slot["nullable"] = True
        review.append(f"{parameter}: nullable named slot")
    else:
        review.append(
            f"{parameter}: required native slot; absence renders an empty lambda"
        )
    slots[parameter] = slot
