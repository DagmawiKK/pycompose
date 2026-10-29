"""How a composable lambda parameter reaches the wire: slots, builders, scopes.

A slot's receiver is handed to its children (ADR-0055); a keyed slot draws one
subtree per key (ADR-0057); a lazy list's builder lists its items. Every other
function parameter needs a protocol the planner records as a gap.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from pycompose_codegen.derive.classpath_dump import Declaration
from pycompose_codegen.derive.classpath_types import KotlinType
from pycompose_codegen.derive.keyed import keyed_arguments


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


def slot_rule(value: KotlinType) -> dict[str, Any]:
    """Classify a composable lambda as a scoped, unscoped or consuming slot.

    A receiver the lambda carries is handed to the children, so a child that
    composes only inside it can (ADR-0016 decision 1); one that needs none
    composes as it would anywhere.
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
    elif arguments:
        raise ValueError("slot-supplied arguments need typed context references")
    return rule


def builder_rule(value: KotlinType) -> dict[str, Any]:
    """A lazy list's builder lambda: the children are the items it lists."""
    receiver = value.arguments[0][1]
    if receiver is None or receiver.classifier != LAZY_LIST or receiver.nullable:
        named = receiver.classifier if receiver is not None else "unresolved"
        raise ValueError(f"builder scope needs a native protocol: {named}")
    return {"policy": "slot", "receiver": None, "kind": "items"}


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
