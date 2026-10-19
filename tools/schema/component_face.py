"""Derive the native argument face an approved component entry passes.

The face is what the generated adapter writes: props by their camelCase name,
provider parameters, children, slots, interaction sources, state and transient
holders, plus the reshaped-prop rules. A reshaped prop carrying ``content``
becomes its named parameter or the trailing composer lambda; any other
reshaped prop is forwarded when the pin declares that name, and is otherwise
host-consumed by hand-written code.

Every argument keeps enough of its Kotlin shape -- classifier, lambda arity,
extension receiver -- that :func:`binds` can say whether one pinned parameter
could accept it, and :func:`accepts` can say whether one pinned declaration
can carry the entry's whole call.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if __package__ in (None, ""):  # pragma: no cover - only when run as a script
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from pycompose.core.registry_types import SCOPE_PATHS
from pycompose.schema.codegen.adapter_helpers import (
    STATE_ATTACH_GATES,
    STATE_CONSTRUCTOR_PROPS,
    _camel,
)
from tools.schema.classpath_dump import Declaration
from tools.schema.propose_lookup import source_name

MODIFIER = "androidx.compose.ui.Modifier"
INTERACTION_SOURCE = "androidx.compose.foundation.interaction.MutableInteractionSource"
ITEMS_RECEIVER = "androidx.compose.foundation.lazy.LazyListScope"
COMPOSABLE = "androidx/compose/runtime/Composable"
COLOR = "androidx.compose.ui.graphics.Color"
DP = "androidx.compose.ui.unit.Dp"
NUMERIC = frozenset({"kotlin.Int", "kotlin.Long", "kotlin.Float", "kotlin.Double"})
"""Kotlin types a wire ``number``/``integer`` prop can reach through coercion."""

DIRECT_ARGUMENTS = {
    "modifier": ("modifier", MODIFIER),
    "color": ("value", COLOR),
    "dp": ("value", DP),
    "string": ("value", "kotlin.String"),
    "boolean": ("value", "kotlin.Boolean"),
    "integer": ("value", "kotlin.Int"),
    "number": ("numeric", "kotlin.Double"),
}
"""Wire prop types whose native argument the type alone decides."""

DECODE_CLASSIFIERS = {
    "alignment": "androidx.compose.ui.Alignment",
    "horizontal": "androidx.compose.ui.Alignment.Horizontal",
    "vertical": "androidx.compose.ui.Alignment.Vertical",
    "arrangement": "androidx.compose.foundation.layout.Arrangement.Vertical",
    "textStyle": "androidx.compose.ui.text.TextStyle",
    "color": COLOR,
}
"""Wire decode tokens whose pinned Kotlin type is fixed by the decoder table."""


@dataclass(frozen=True)
class Argument:
    """One native argument the generated adapter would pass.

    Attributes:
        name: The native parameter name.
        kind: ``modifier``, ``function``, ``value``, ``numeric``, or ``unknown``.
        classifier: The declared Kotlin type, when the wire rule fixes one.
        arity: The number of value parameters the lambda carries.
        receiver: The lambda's extension receiver, when it has one.
        returns: The provider lambda's return type simple name, when it has one.
    """

    name: str
    kind: str
    classifier: str | None = None
    arity: int | None = None
    receiver: str = ""
    returns: str | None = None


@dataclass(frozen=True)
class Face:
    """The native arguments an entry's generated call passes.

    Attributes:
        arguments: The named arguments, sorted by name.
        anonymous: Whether a reshaped content prop fills the trailing lambda.
        host: Reshaped props the hand-written code resolves and never names.
        problems: Prop-level reasons the face is not fully expressible.
    """

    arguments: tuple[Argument, ...]
    anonymous: bool
    host: tuple[str, ...]
    problems: tuple[str, ...]


def family_types(registry: dict[str, Any]) -> dict[str, str]:
    """Map every public value family to the pin's Kotlin type.

    Args:
        registry: The approved component registry.

    Returns:
        Family names as component entries spell them, keyed to the pinned
        Kotlin type.
    """
    return {
        spec["family"]: source_name(spec["kotlinType"])
        for spec in registry.get("valueTypes", {}).values()
        if "family" in spec and "kotlinType" in spec
    }


def _prop_argument(
    name: str, spec: dict[str, Any], families: dict[str, str]
) -> Argument:
    """Turn one approved prop rule into the native argument it reaches."""
    kind = spec["type"]
    if kind in {"value", "enum"} and "valueType" in spec:
        family = spec["valueType"]
        return Argument(name, "value", families.get(family, family))
    if kind == "enum" and spec.get("decode") in DECODE_CLASSIFIERS:
        return Argument(name, "value", DECODE_CLASSIFIERS[spec["decode"]])
    if kind == "actionId":
        return Argument(name, "function", arity=len(spec.get("payload", [])))
    direct = DIRECT_ARGUMENTS.get(kind)
    if direct is not None:
        return Argument(name, direct[0], direct[1])
    return Argument(name, "unknown")


def _held(entry: dict[str, Any]) -> set[str]:
    """The wire props the host holds rather than passes to the native call."""
    state = entry.get("state")
    held: set[str] = set()
    if state:
        held |= {state["value"], state["report"]}
        held |= set(STATE_CONSTRUCTOR_PROPS.get(state["kind"], ()))
        gate = STATE_ATTACH_GATES.get(state["kind"])
        if gate:
            held.add(gate)
    if entry.get("transient"):
        held |= set(entry.get("props", {}))
    return held


def _prop_face(
    entry: dict[str, Any], families: dict[str, str], pin_names: frozenset[str]
) -> tuple[dict[str, Argument], bool, list[str], list[str]]:
    """Derive the prop half of the face: named args, content, host, problems."""
    interaction = entry.get("interaction") or {}
    observed = set((interaction.get("observations") or {}).values())
    held = _held(entry) | observed
    reshaped = set(entry.get("reshaped", []))
    named: dict[str, Argument] = {}
    anonymous = False
    host: list[str] = []
    problems: list[str] = []
    for prop, spec in entry.get("props", {}).items():
        if prop in held:
            continue
        if "provider" in spec:
            native = spec["provider"]["native"]
            named[native] = Argument(
                native, "function", arity=0, returns=spec["provider"]["returns"]
            )
            # The provider's closure is the whole argument: the prop's own name
            # is not also passed, and ``provider_errors`` checks the pinned
            # parameter the closure meets.
            continue
        if spec.get("content"):
            parameter = spec["content"].get("parameter")
            if parameter:
                named[parameter] = Argument(parameter, "function", arity=0)
            else:
                anonymous = True
            continue
        native = _camel(prop)
        if prop in reshaped and native not in pin_names:
            host.append(prop)
            continue
        if native not in pin_names:
            problems.append(f"{prop}: no parameter in any pinned overload")
        named[native] = _prop_argument(native, spec, families)
    return named, anonymous, host, problems


def _wiring_face(
    entry: dict[str, Any], pin_names: frozenset[str]
) -> tuple[dict[str, Argument], list[str]]:
    """Derive the wiring half of the face: children, slots, state, transient."""
    named: dict[str, Argument] = {}
    problems: list[str] = []

    def add(label: str, name: str, argument: Argument) -> None:
        named[name] = argument
        if name not in pin_names:
            problems.append(f"{label}: {name!r} is not pinned")

    children = entry.get("children", {})
    if children.get("allowed"):
        name = children.get("native", "content")
        provides = children.get("provides")
        if children.get("kind") == "items":
            receiver = ITEMS_RECEIVER
        else:
            receiver = (SCOPE_PATHS.get(provides, provides) or "") if provides else ""
        add(
            "children",
            name,
            Argument(
                name,
                "function",
                arity=1 if children.get("consume") else 0,
                receiver=receiver,
            ),
        )
    for slot in entry.get("slots", {}).values():
        add(
            "slots",
            slot["native"],
            Argument(slot["native"], "function", arity=1 if slot.get("consume") else 0),
        )
    interaction = entry.get("interaction") or {}
    if interaction:
        name = interaction["native"]
        add("interaction", name, Argument(name, "value", INTERACTION_SOURCE))
    state = entry.get("state")
    if state and state["kind"] not in STATE_ATTACH_GATES:
        add("state", state["native"], Argument(state["native"], "value"))
    if state and state.get("dismiss"):
        name = state["dismiss"]
        add("state.dismiss", name, Argument(name, "function", arity=0))
    transient = entry.get("transient")
    if transient:
        name = transient["native"]
        add("transient", name, Argument(name, "value"))
    return named, problems


def face(
    entry: dict[str, Any], registry: dict[str, Any], pin_names: frozenset[str]
) -> Face:
    """Derive the native argument face one entry's generated call passes.

    Args:
        entry: The approved component entry.
        registry: The approved component registry, for value families.
        pin_names: Every parameter name the entry's package declares for the
            component, so a reshaped prop the pin actually names is forwarded
            rather than treated as host-consumed.

    Returns:
        The face the entry claims.
    """
    families = family_types(registry)
    prop_args, anonymous, host, prop_problems = _prop_face(entry, families, pin_names)
    wiring_args, wiring_problems = _wiring_face(entry, pin_names)
    named: dict[str, Argument] = {
        "modifier": Argument("modifier", "modifier", MODIFIER)
    }
    named.update(prop_args)
    named.update(wiring_args)
    return Face(
        arguments=tuple(named[name] for name in sorted(named)),
        anonymous=anonymous,
        host=tuple(sorted(host)),
        problems=tuple(prop_problems + wiring_problems),
    )


def _binds_value(
    argument: Argument, classifier: str, hierarchy: dict[str, set[str]]
) -> bool:
    """Whether one value argument reaches the parameter's declared type."""
    if argument.classifier is None:
        return True
    wanted = source_name(argument.classifier)
    return classifier == wanted or classifier in hierarchy.get(wanted, set())


def _binds_provider(argument: Argument, arguments: list[Any]) -> bool:
    """Whether one provider closure returns the wire type it declares."""
    if argument.receiver or not arguments:
        return False
    pinned = source_name(arguments[-1].classifier).rsplit(".", 1)[-1]
    return argument.arity == len(arguments) - 1 and pinned == argument.returns


def _binds_closure(argument: Argument, parameter: Any, arguments: list[Any]) -> bool:
    """Whether one content or callback lambda reaches the declared type."""
    extension = "kotlin/ExtensionFunctionType" in parameter.type.annotations
    if not extension:
        return argument.arity == len(arguments) - 1 and not argument.receiver
    if not arguments:
        return False
    if argument.arity != len(arguments) - 2:
        return False
    # A lambda literal adapts to the expected receiver: only a declared
    # receiver has to agree with the pin.
    if not argument.receiver:
        return True
    return source_name(arguments[0].classifier) == argument.receiver


def _binds_function(argument: Argument, parameter: Any, classifier: str) -> bool:
    """Whether one lambda argument reaches the parameter's declared type."""
    if not classifier.startswith("kotlin.Function"):
        return False
    arguments = [type_ for _, type_ in parameter.type.arguments if type_ is not None]
    if argument.returns is not None:
        return _binds_provider(argument, arguments)
    if arguments and source_name(arguments[-1].classifier) != "kotlin.Unit":
        return False
    return _binds_closure(argument, parameter, arguments)


def binds(argument: Argument, parameter: Any, hierarchy: dict[str, set[str]]) -> bool:
    """Report whether one face argument can bind one native parameter.

    Args:
        argument: The declared argument the generated call would pass.
        parameter: The pinned parameter it would meet.
        hierarchy: Class ancestry over the pin, as ``propose_lookup`` builds it.

    Returns:
        Whether Kotlin's overload resolution could use this parameter.
    """
    classifier = source_name(parameter.type.classifier)
    if argument.kind == "modifier":
        return classifier == MODIFIER
    if argument.kind == "numeric":
        return classifier in NUMERIC
    if argument.kind == "function":
        return _binds_function(argument, parameter, classifier)
    if argument.kind == "value":
        return _binds_value(argument, classifier, hierarchy)
    return True


def _content_parameter(
    declaration: Declaration, forwarded: set[str], native: str
) -> Any | None:
    """The pinned content lambda an anonymous trailing lambda fills."""
    spare = [
        parameter
        for parameter in declaration.parameters
        if parameter.name not in forwarded
        and parameter.name == native
        and parameter.type.classifier.startswith("kotlin/Function")
        and COMPOSABLE in parameter.type.annotations
    ]
    return spare[0] if len(spare) == 1 else None


def _has_receiver(declaration: Declaration, scope: str) -> bool:
    """Whether one declaration is an extension on the named composition scope."""
    path = SCOPE_PATHS.get(scope, "").replace(".", "/")
    return declaration.receiver is not None and declaration.receiver.classifier == path


def accepts(
    declaration: Declaration,
    derived: Face,
    entry: dict[str, Any],
    hierarchy: dict[str, set[str]],
) -> bool:
    """Whether one pinned declaration can carry the entry's whole call.

    Args:
        declaration: The pinned declaration under test.
        derived: The face the entry's generated call passes.
        entry: The approved component entry.
        hierarchy: Class ancestry over the pin, computed once by the caller.

    Returns:
        Whether every required parameter is forwarded and every forwarded
        argument can bind the parameter it meets.
    """
    if entry.get("scope") and not _has_receiver(declaration, entry["scope"]):
        return False
    forwarded = {argument.name for argument in derived.arguments}
    if derived.anonymous:
        content = _content_parameter(
            declaration, forwarded, entry.get("children", {}).get("native", "content")
        )
        if content is None:
            return False
        forwarded.add(content.name)
    parameters = {parameter.name: parameter for parameter in declaration.parameters}
    if {p.name for p in declaration.parameters if p.required} - forwarded:
        return False
    if not forwarded <= set(parameters):
        return False
    return all(
        binds(argument, parameters[argument.name], hierarchy)
        for argument in derived.arguments
    )
