"""Holder families the pin derives: their checks and the locals an adapter writes.

A positional holder (a pager's page) and an anchored one (a drawer open or
closed) carry everything the host needs in their component's ``state``: the
pinned factory, what it starts at, what to read back and how to drive it.
Codegen checks that and writes it into the adapter as typed lambdas the host's
one runtime for the family runs (``Positional.kt``, ``Anchored.kt``).
"""

from __future__ import annotations

from typing import Any

from pycompose_codegen.emit.adapters.policy import camel
from pycompose_codegen.emit.defaults import render_default
from pycompose_codegen.emit.rules import die
from pycompose_codegen.emit.state_families import (
    anchored_props,
    attach_gate,
    positional_props,
    settled_name,
)

POSITIONAL_KEYS = frozenset(
    {
        "native",
        "kind",
        "holder",
        "factory",
        "initial",
        "count",
        "position",
        "drive",
        "spec",
        "snap",
    }
)


def validate_positional(
    where: str, props: dict[str, Any], state: dict[str, Any]
) -> None:
    """Check a positional family: its pinned members, and the props it projects.

    Args:
        where: Prefix for error messages.
        props: The component's props, which must carry the projection.
        state: The raw ``state`` object of kind ``positional``.
    """
    unknown = sorted(set(state) - POSITIONAL_KEYS)
    if unknown:
        die(f"{where} has unknown keys: {', '.join(unknown)}")
    for key in POSITIONAL_KEYS - {"count", "spec", "snap"}:
        if not isinstance(state.get(key), str) or not state[key]:
            die(f"{where}: positional needs {key!r}")
    if positional_props(state).keys() - props.keys():
        die(f"{where}: the position and its report must be among the props")
    gate = attach_gate(state, props)
    if gate is not None and props[gate].get("type") != "boolean":
        die(f"{where}: prop {gate!r} must be a boolean")


ANCHORED_KEYS = frozenset(
    {
        "native",
        "kind",
        "holder",
        "factory",
        "valueClass",
        "anchors",
        "settled",
        "started",
        "functions",
    }
)


def validate_anchored(where: str, props: dict[str, Any], state: dict[str, Any]) -> None:
    """Check an anchored family: its pinned members, anchors, and projected props.

    Args:
        where: Prefix for error messages.
        props: The component's props, which must carry the projection.
        state: The raw ``state`` object of kind ``anchored``.
    """
    unknown = sorted(set(state) - ANCHORED_KEYS)
    if unknown:
        die(f"{where} has unknown keys: {', '.join(unknown)}")
    for key in ANCHORED_KEYS - {"anchors", "started", "functions"}:
        if not isinstance(state.get(key), str) or not state[key]:
            die(f"{where}: anchored needs {key!r}")
    if not isinstance(state.get("anchors"), dict) or not state["anchors"]:
        die(f"{where}: anchored needs its anchors")
    if anchored_props(state).keys() - props.keys():
        die(f"{where}: the value and its report must be among the props")


def positional_locals(state: dict[str, Any]) -> list[str]:
    """A positional family: the host's one runtime, told how to make and drive it.

    Its positions are the children Python sent, so the count the factory asks
    for is theirs.

    Args:
        state: A ``state`` block of kind ``positional``.

    Returns:
        The Kotlin locals.
    """
    native, position, drive = state["native"], state["position"], state["drive"]
    count = f", {state['count']} = count" if "count" in state else ""
    create = f"{state['factory']}({state['initial']} = initial{count})"
    report = camel(settled_name(position))
    if "snap" in state:
        # A bound position: it follows through the snap, travels with its spec.
        desired = f"model.props.{camel(position)}"
        snap = f"{{ holder, target -> holder.{state['snap']}(target) }}"
        driven = (
            f"if (spec == null) holder.{drive}(target) "
            f"else holder.{drive}(target, {state['spec']} = spec)"
        )
        arguments = "holder, target, spec"
    else:
        desired = f"model.props.{camel(position)}?.let(::JsonPrimitive)"
        snap, driven, arguments = "null", f"holder.{drive}(target)", "holder, target, _"
    return [
        f"val {native}Value = context.positional(",
        f"    {desired}, model.props.{report},",
        "    model.children.unslotted().size,",
        "    com.pycompose.renderer.Positional(",
        f"        {{ initial, {'count' if count else '_'} -> {create} }},",
        f"        {{ it.{position} }},",
        f"        {snap},",
        f"    ) {{ {arguments} -> {driven} }},",
        ")",
    ]


def anchored_locals(state: dict[str, Any]) -> list[str]:
    """An anchored family: the host's one runtime, told its anchors and members.

    Where the factory has its own start, an unstated anchor leaves it to that.

    Args:
        state: A ``state`` block of kind ``anchored``.

    Returns:
        The Kotlin locals.
    """
    native, enum, factory = state["native"], state["valueClass"], state["factory"]
    values = ", ".join(
        f'"{wire}" to {enum}.{entry}' for wire, entry in state["anchors"].items()
    )
    functions = state.get("functions", {})
    locals_ = [line for n, f in functions.items() for line in _function_locals(n, f)]
    passed = "".join(f", {name} = {name}Value" for name in functions)
    at = f"{factory}(initialValue = it{passed})"
    create = (
        f"{{ initial -> initial?.let {{ {at} }} ?: {factory}({passed[2:]}) }}"
        if state.get("started")
        else f"{{ initial -> {factory}(initialValue = checkNotNull(initial){passed}) }}"
    )
    return [
        *locals_,
        f"val {native}Value = context.anchoredState(",
        "    model.props.value, model.props.onValueChange,",
        "    com.pycompose.renderer.Anchors(",
        f"        mapOf({values}),",
        f"        {create},",
        f"        {{ it.{state['settled']} }},",
        "    ) { holder, anchor -> holder.driveTo(anchor) },",
        ")",
    ]


GIVEN = {
    "string": "{}.wire",
    "kotlin.Float": "{}.toDouble()",
    "kotlin.Int": "{}.toLong()",
}
"""How the host hands an argument to a program: an anchor as its wire spelling,
a Float as a number, an Int as an integer; the rest as they are."""

ANSWERED = {
    "kotlin.Float": "(it as Double).toFloat()",
    "kotlin.Int": "(it as Long).toInt()",
}
"""How a program's answer becomes the native one; the rest are cast as they are."""


def _function_locals(name: str, function: dict[str, Any]) -> list[str]:
    """One factory function argument: the app's host function, else the default.

    The factory keeps the lambda it is created with, so the lambda reads the
    app's latest function each call rather than the one it was created with.

    Args:
        name: The factory parameter, which is also the prop.
        function: Its derived arguments, answer and default.

    Returns:
        The Kotlin locals ending in ``<name>Value``, the lambda to pass.
    """
    imports: set[str] = set()
    default = render_default(function["default"], imports)
    if imports:
        die(f"{name}: a factory function's default needs no import")
    arguments = function["payload"]
    names = [f"a{i}" for i in range(len(arguments))]
    natives = ", ".join(a["native"] for a in arguments)
    kind = f"({natives}) -> {function['native']}"
    given = ", ".join(
        GIVEN.get(a["type"] if a["type"] == "string" else a["native"], "{}").format(n)
        for n, a in zip(names, arguments, strict=True)
    )
    answered = ANSWERED.get(function["native"], f"it as {function['native']}")
    head = ", ".join(f'"{a["type"]}"' for a in arguments)
    return [
        f"val {name}Answer = rememberFunction(",
        f'    model.props.{name}, listOf({head}), "{function["result"]}",',
        ")",
        f"val {name}Default: {kind} = {default}",
        f"val {name}Value: {kind} = {{ {', '.join(names)} ->",
        f"    {name}Answer.value?.call({given})?.let {{ {answered} }}"
        f" ?: {name}Default({', '.join(names)})",
        "}",
    ]
