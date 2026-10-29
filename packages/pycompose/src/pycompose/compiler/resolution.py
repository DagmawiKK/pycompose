"""Kotlin overload resolution among call plans (spec 11.6).

Every representable argument is passed explicitly, so the arguments a call
carries are what Kotlin resolves on. An overload whose arguments another
overload's call also accepts competes with it; the planner refuses one that
cannot be told apart rather than bind it silently to a sibling.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Set as AbstractSet
from typing import Any, NamedTuple

MODIFIER = "androidx/compose/ui/Modifier"


class DeclaredType(NamedTuple):
    """Kotlin type of a prop as overload selection compares it."""

    kind: str
    classifier: str
    nullable: bool
    composable: bool = False
    receiver: str = ""
    arity: int = 0


def _forwarded(candidate: dict[str, Any]) -> frozenset[str]:
    """Names a generated call passes, which is what Kotlin resolves on."""
    return frozenset(
        name
        for name, spec in candidate["parameters"].items()
        if spec["policy"] not in {"omit", "blocked"}
    )


def _declared_type(spec: dict[str, Any]) -> DeclaredType:
    """Describe the Kotlin type a prop declares, for overload selection."""
    doc = spec["type"]
    arguments = [a["type"] for a in doc["arguments"] if a["type"] is not None]
    if spec["policy"] in {"event", "slot"} or doc["classifier"].startswith(
        "kotlin/Function"
    ):
        receiver = ""
        if "kotlin/ExtensionFunctionType" in doc["annotations"] and arguments:
            receiver = arguments.pop(0)["classifier"]
        return DeclaredType(
            kind="function",
            classifier="kotlin/Function",
            nullable=doc["nullable"],
            composable="androidx/compose/runtime/Composable" in doc["annotations"],
            receiver=receiver,
            arity=len(arguments),
        )
    return DeclaredType(
        kind="value",
        classifier=MODIFIER if spec["policy"] == "modifier" else doc["classifier"],
        nullable=doc["nullable"],
    )


def _assignable(argument: DeclaredType, parameter: DeclaredType) -> bool:
    """Report whether the argument a call passes can bind that parameter."""
    if argument.kind != parameter.kind:
        return False
    if not (
        argument.nullable == parameter.nullable
        or (parameter.nullable and not argument.nullable)
    ):
        return False
    if argument.kind == "function":
        # A composable lambda is a distinct type kind, and arity/receiver must
        # match for the lambda to be accepted at all.
        return (argument.composable, argument.receiver, argument.arity) == (
            parameter.composable,
            parameter.receiver,
            parameter.arity,
        )
    return argument.classifier == parameter.classifier


def competing(candidate: dict[str, Any], other: dict[str, Any]) -> bool:
    """Report whether a call carrying this overload's arguments could bind to ``other``.

    Kotlin applies ``other`` only when every argument it is given names one of its
    parameters, is type-compatible with it, and every required parameter it declares
    is among them. A parameter the call leaves unsupplied keeps the overload out of
    the candidate set, however similar the argument lists look. Of two applicable
    candidates equally specific by type, the one using fewer defaults is chosen.
    """
    if _receiver(candidate) != _receiver(other):
        # An extension on a scope applies only where that scope is the implicit
        # receiver, and wins there; a top-level overload is the only one
        # elsewhere. The two never compete for one call.
        return False
    mine = _forwarded(candidate)
    if not mine <= set(other["parameters"]):
        return False
    required = {name for name, spec in other["parameters"].items() if spec["required"]}
    if not required <= mine:
        return False
    theirs = {name: _declared_type(other["parameters"][name]) for name in mine}
    ours = {name: _declared_type(candidate["parameters"][name]) for name in mine}
    if not all(_assignable(ours[name], theirs[name]) for name in mine):
        return False
    # Equally specific by type, Kotlin picks the candidate leaving the fewest
    # default parameters unspecified (spec 11.6); then this one wins.
    return ours != theirs or _unspecified(other, mine) <= _unspecified(candidate, mine)


def _receiver(plan: dict[str, Any]) -> str | None:
    receiver = plan.get("receiver")
    return receiver["classifier"] if receiver else None


def _unspecified(plan: dict[str, Any], passed: AbstractSet[str]) -> int:
    """Default parameters a call passing ``passed`` leaves to their defaults."""
    return sum(
        1
        for name, spec in plan["parameters"].items()
        if spec["hasDefault"] and name not in passed
    )


def block_unaddressable_overloads(candidates: list[dict[str, Any]]) -> None:
    """Refuse an overload no named-argument call can select uniquely.

    Two same-named overloads are only addressable when the arguments a call passes
    tell them apart. If a sibling accepts exactly the arguments this overload would
    pass, the recorded JVM identity is not what a compiler resolves to.
    """
    groups = defaultdict(list)
    for candidate in candidates:
        groups[candidate["call"]].append(candidate)
    for group in groups.values():
        if len(group) < 2:
            continue
        for candidate in group:
            if candidate["status"] != "call-plan":
                # Already refused for a capability this overload needs; a second
                # identity reason would not add information.
                continue
            if any(
                competing(candidate, other) for other in group if other is not candidate
            ):
                candidate["gaps"].append(
                    {
                        "parameter": None,
                        "required": True,
                        "reason": (
                            "overload identity is not addressable by named arguments"
                        ),
                    }
                )
                candidate["status"] = "blocked"
