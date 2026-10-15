"""Lower Python binding declarations to wire strings and immutable metadata."""

from collections.abc import Mapping
from typing import cast

from pycompose.core.action_binding import ActionBinding
from pycompose.core.node import Node, Props
from pycompose.core.props import JsonValue
from pycompose.core.traversal import walk_nodes
from pycompose.errors import IrValidationError


def _declare(contracts: dict[str, object], binding: ActionBinding) -> str:
    """Record one binding contract and return its stable wire id.

    Args:
        contracts: Accumulated declarations by binding id.
        binding: Python-side declaration to lower.

    Returns:
        The binding id exactly as it appears on the wire.

    Raises:
        IrValidationError: If one id declares two incompatible contracts.
    """
    key = str(binding)
    wire = binding.spec.to_wire()
    if key in contracts and contracts[key] != wire:
        raise IrValidationError("conflicting app binding id", binding_id=key)
    contracts[key] = wire
    return key


def lower_bindings(root: Node) -> tuple[Node, Mapping[str, JsonValue] | None]:
    """Extract binding contracts without altering untouched native branches.

    Args:
        root: Expanded native graph, potentially carrying action declarations.

    Returns:
        Native graph and optional binding metadata containing no Python handlers.
    """
    contracts: dict[str, object] = {}
    frames: list[list[Node]] = []
    result = root

    for source, entering in walk_nodes(root):
        if entering:
            frames.append([])
            continue
        children = frames.pop()
        props = source.props
        bindings = {
            key: value
            for key, value in props.values.items()
            if isinstance(value, ActionBinding)
        }
        modifier = props.values.get("modifier")
        operations = (
            modifier.get("operations", ()) if isinstance(modifier, Mapping) else ()
        )
        modifier_bindings = isinstance(operations, tuple | list) and any(
            isinstance(operation, Mapping)
            and isinstance(operation.get("onClick"), ActionBinding)
            for operation in operations
        )
        if bindings or modifier_bindings:
            wire_props = props.to_wire()
            for key, binding in bindings.items():
                wire_props[key] = _declare(contracts, binding)
            if modifier_bindings:
                wire_modifier = cast("dict[str, JsonValue]", wire_props["modifier"])
                for operation in cast(
                    "list[dict[str, JsonValue]]", wire_modifier["operations"]
                ):
                    click = operation.get("onClick")
                    if isinstance(click, ActionBinding):
                        operation["onClick"] = _declare(contracts, click)
            props = Props(wire_props)
        unchanged = props is source.props and all(
            a is b for a, b in zip(children, source.children, strict=True)
        )
        result = (
            source
            if unchanged
            else Node(
                id=source.id,
                type=source.type,
                props=props,
                children=children,
                slot=source.slot,
            )
        )
        if frames:
            frames[-1].append(result)
    metadata = {"actionBindings": contracts} if contracts else None
    return result, cast("Mapping[str, JsonValue] | None", metadata)
