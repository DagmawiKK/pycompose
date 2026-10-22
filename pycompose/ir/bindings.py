"""Lower Python binding declarations to wire strings and immutable metadata."""

from collections.abc import Callable, Mapping
from typing import cast

from pycompose.core.action_binding import ActionBinding
from pycompose.core.node import Props
from pycompose.core.props import JsonValue
from pycompose.errors import IrValidationError
from pycompose.utils.json_canonical import freeze_json

Declare = Callable[[str, object], None]
"""Records one binding id and its wire contract."""


def record(contracts: dict[str, object], key: str, wire: object) -> None:
    """Record one binding contract, refusing a second, different one for its id.

    Args:
        contracts: Accumulated declarations by binding id.
        key: The binding id exactly as it appears on the wire.
        wire: Its contract.

    Raises:
        IrValidationError: If one id declares two incompatible contracts.
    """
    if key in contracts and contracts[key] != wire:
        raise IrValidationError("conflicting app binding id", binding_id=key)
    contracts[key] = wire


def lower_props(props: Props, declare: Declare) -> Props:
    """Replace one node's binding declarations by their wire ids.

    Args:
        props: The node's props, possibly carrying action declarations.
        declare: Receives each binding's id and wire contract.

    Returns:
        The same props when nothing is bound, else props holding only wire data.
    """
    bindings = {
        key: value
        for key, value in props.values.items()
        if isinstance(value, ActionBinding)
    }
    modifier = props.values.get("modifier")
    operations = modifier.get("operations", ()) if isinstance(modifier, Mapping) else ()
    modifier_bindings = isinstance(operations, tuple | list) and any(
        isinstance(operation, Mapping)
        and isinstance(operation.get("onClick"), ActionBinding)
        for operation in operations
    )
    if not bindings and not modifier_bindings:
        return props

    def wire(binding: ActionBinding) -> str:
        key = str(binding)
        # Frozen once here, so the contract keeps its identity in metadata.
        declare(key, freeze_json(binding.spec.to_wire()))
        return key

    wire_props = props.to_wire()
    for key, binding in bindings.items():
        wire_props[key] = wire(binding)
    if modifier_bindings:
        wire_modifier = cast("dict[str, JsonValue]", wire_props["modifier"])
        operations_wire = cast(
            "list[dict[str, JsonValue]]", wire_modifier["operations"]
        )
        for operation in operations_wire:
            click = operation.get("onClick")
            if isinstance(click, ActionBinding):
                operation["onClick"] = wire(click)
    return Props(wire_props)
