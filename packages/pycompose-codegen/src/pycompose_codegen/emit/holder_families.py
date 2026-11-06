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
from pycompose_codegen.emit.rules import die
from pycompose_codegen.emit.state_families import (
    anchored_props,
    positional_props,
    settled_name,
)

POSITIONAL_KEYS = frozenset(
    {"native", "kind", "holder", "factory", "initial", "count", "position", "drive"}
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
    for key in POSITIONAL_KEYS - {"count"}:
        if not isinstance(state.get(key), str) or not state[key]:
            die(f"{where}: positional needs {key!r}")
    if positional_props(state).keys() - props.keys():
        die(f"{where}: the position and its report must be among the props")


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
    for key in ANCHORED_KEYS - {"anchors", "started"}:
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
    native, position = state["native"], state["position"]
    count = f", {state['count']} = count" if "count" in state else ""
    create = f"{state['factory']}({state['initial']} = initial{count})"
    report = camel(settled_name(position))
    return [
        f"val {native}Value = context.positional(",
        f"    model.props.{camel(position)}, model.props.{report},",
        "    model.children.unslotted().size,",
        "    com.pycompose.renderer.Positional(",
        f"        {{ initial, count -> {create} }},",
        f"        {{ it.{position} }},",
        f"    ) {{ holder, target -> holder.{state['drive']}(target) }},",
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
    at = f"{factory}(initialValue = it)"
    create = (
        f"{{ initial -> initial?.let {{ {at} }} ?: {factory}() }}"
        if state.get("started")
        else f"{{ initial -> {factory}(initialValue = checkNotNull(initial)) }}"
    )
    return [
        f"val {native}Value = context.anchoredState(",
        "    model.props.value, model.props.onValueChange,",
        "    com.pycompose.renderer.Anchors(",
        f"        mapOf({values}),",
        f"        {create},",
        f"        {{ it.{state['settled']} }},",
        "    ) { holder, anchor -> holder.driveTo(anchor) },",
        ")",
    ]
