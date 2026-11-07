"""How a lambda parameter reaches the wire: slots, builders, events, drawings.

A slot's receiver is handed to its children (ADR-0055); a keyed slot draws one
subtree per key (ADR-0057); a lazy list's builder lists its items; a callback
dispatches an event; a canvas's draw lambda runs a draw program. Every other
function parameter needs a protocol the planner records as a gap.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from pycompose_codegen.derive.classpath_dump import Declaration
from pycompose_codegen.derive.classpath_types import BUILDERS, Kind, KotlinType
from pycompose_codegen.derive.keyed import keyed_arguments
from pycompose_codegen.derive.propose import SCALARS


def function_arguments(value: KotlinType) -> list[KotlinType]:
    """Return the synchronous arguments a native function type receives."""
    if (
        value.suspend
        or not value.arguments
        or any(t is None for _, t in value.arguments)
    ):
        raise ValueError("unresolved/suspending function needs a native protocol")
    arguments = [t for _, t in value.arguments if t is not None]
    if arguments[-1].classifier != "kotlin/Unit" or arguments[-1].nullable:
        raise ValueError("synchronous result needs a provider/predicate protocol")
    return arguments[:-1]


CONSUMED = {"androidx/compose/foundation/layout/PaddingValues": "paddingValues"}
"""Slot arguments the adapter applies on the subtree's behalf (``CONSUMERS``)."""

LAZY_LIST = "androidx/compose/foundation/lazy/LazyListScope"

Holders = dict[str, dict[str, Any]]
"""What the pin derives per type: holder families, item scopes, handed holders."""


def slot_rule(value: KotlinType, holders: Holders) -> dict[str, Any]:
    """Classify a composable lambda as a scoped, unscoped or consuming slot.

    A receiver the lambda carries is handed to the children, so a child that
    composes only inside it can (ADR-0016 decision 1); one that needs none
    composes as it would anywhere. A holder the lambda is handed, whose
    members set a property (``members.handed_holders``), is projected onto
    the slot's owner.
    """
    arguments = function_arguments(value)
    receiver = None
    if "kotlin/ExtensionFunctionType" in value.annotations:
        if not arguments:
            raise ValueError("missing slot receiver")
        native_receiver = arguments.pop(0)
        if native_receiver.nullable or native_receiver.arguments:
            raise ValueError(
                f"slot scope needs a native protocol: {native_receiver.classifier}"
            )
        receiver = native_receiver.classifier
    rule: dict[str, Any] = {"policy": "slot", "receiver": receiver}
    if keyed_arguments(value):
        rule["keyed"] = True
    elif (
        len(arguments) == 1
        and not arguments[0].nullable
        and arguments[0].classifier in CONSUMED
    ):
        rule["consume"] = CONSUMED[arguments[0].classifier]
    elif [(a.classifier, a.nullable) for a in arguments] == [("kotlin/Int", False)]:
        # A template over an index: Python sends one subtree per index, in order.
        rule["kind"] = "indexed"
    elif (
        len(arguments) == 1
        and not arguments[0].nullable
        and holders.get(arguments[0].classifier, {}).get("kind") == "handed"
    ):
        handed = holders[arguments[0].classifier]
        rule["handed"] = {k: handed[k] for k in ("holder", "value", "drives")}
    elif arguments:
        raise ValueError("slot-supplied arguments need typed context references")
    return rule


def builder_rule(value: KotlinType, holders: Holders) -> dict[str, Any]:
    """A builder lambda: the children are the items it lists, or the members it calls.

    A list, a grid and a staggered grid build alike, one item per child, so
    the host lists them through the same protocol in each scope. A scope whose
    members are items (``members.member_scopes``) takes item components, each
    applied to it as the builder runs.
    """
    receiver = value.arguments[0][1]
    named = receiver.classifier if receiver is not None else "unresolved"
    if receiver is not None and not receiver.nullable and named in BUILDERS:
        return {"policy": "slot", "receiver": None, "kind": "items"}
    if receiver is not None and holders.get(named, {}).get("kind") == "members":
        applies = [s.replace("/", ".") for s in holders[named]["items"]]
        return {
            "policy": "slot",
            "receiver": named,
            "kind": "members",
            "applies": applies,
        }
    raise ValueError(f"builder scope needs a native protocol: {named}")


def scope_providers(
    declarations: Iterable[Declaration], scopes: frozenset[str]
) -> set[str]:
    """Receivers an app composes inside: a builder's own, or a slot's (ADR-0016)."""
    return {d.receiver.classifier for d in declarations if d.receiver} | scopes


def slot_scopes(declarations: Iterable[Declaration]) -> frozenset[str]:
    """Receivers a pinned slot lambda carries: the only ones a host can hand down.

    A declaration on one, or in one, has a parent to compose inside.
    """
    return frozenset(
        receiver.classifier
        for declaration in declarations
        if declaration.composable
        for parameter in declaration.parameters
        if "androidx/compose/runtime/Composable" in parameter.type.annotations
        and "kotlin/ExtensionFunctionType" in parameter.type.annotations
        and parameter.type.arguments
        and (receiver := parameter.type.arguments[0][1]) is not None
        and not receiver.nullable
        and not receiver.arguments
    )


def event_rule(value: KotlinType, _: Holders) -> dict[str, Any]:
    """A callback's binding: its arguments become the event's scalar payload."""
    arguments = function_arguments(value)
    if any(t.classifier not in SCALARS for t in arguments):
        raise ValueError("event payload needs a structured value codec")
    return {
        "policy": "event",
        "payload": [
            {"name": f"arg{i}", "type": SCALARS[t.classifier], "nullable": t.nullable}
            for i, t in enumerate(arguments)
        ],
    }


def draw_rule(_: KotlinType, __: Holders) -> dict[str, Any]:
    """A canvas's draw lambda: a draw program the host runs every frame."""
    return {"policy": "draw"}


LAMBDA_RULES: dict[Kind, Callable[[KotlinType, Holders], dict[str, Any]]] = {
    Kind.SLOT: slot_rule,
    Kind.BUILDER: builder_rule,
    Kind.CALLBACK: event_rule,
    Kind.DRAW: draw_rule,
}
"""How each kind of lambda parameter reaches the wire."""

PROGRAM_INTERFACES = {"androidx/compose/ui/layout/MeasurePolicy": "layout"}
"""Interfaces a host program implements, by the program kind that does."""
