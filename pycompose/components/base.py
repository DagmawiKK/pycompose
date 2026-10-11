"""Thin, immutable component construction driven by generated registry tables."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import ClassVar, cast

from pycompose.components.modifiers import Modifier
from pycompose.core import Node, Props
from pycompose.core.props import JsonValue, props_from_kwargs, to_snake_case
from pycompose.errors import IrValidationError
from pycompose.ir.validator import validate_component
from pycompose.utils.json_canonical import FrozenJsonValue, freeze_json


class Component(Node):
    """A Node with a registered component type and Pythonic prop names.

    Explicit ids are stable sibling keys. No automatic counters or object ids
    participate in composition. Emission produces plain IR Nodes when ids change.
    """

    __slots__ = ()
    component_type: ClassVar[str]

    def __init__(
        self,
        *,
        id: str,
        children: Sequence[Node] = (),
        modifier: Modifier | Mapping[str, JsonValue | FrozenJsonValue] | None = None,
        **props: JsonValue,
    ) -> None:
        """Construct immutable IR and validate this component, not its subtree.

        Args:
            id: Stable sibling key or already-qualified node id.
            children: Child nodes in render order.
            modifier: Ordered Modifier or a modifier wire object.
            **props: Snake_case props declared by the component registry.

        Raises:
            IrValidationError: If a prop name is not snake_case.
        """
        for name in props:
            if name != to_snake_case(name):
                raise IrValidationError(
                    "prop name is not snake_case", node_id=id, prop=name
                )
        wire = cast(
            "dict[str, JsonValue | FrozenJsonValue]", props_from_kwargs(**props)
        )
        if modifier is not None:
            wire["modifier"] = freeze_json(
                modifier.values if isinstance(modifier, Modifier) else modifier
            )
        super().__init__(
            id=id, type=self.component_type, props=Props(wire), children=children
        )
        validate_component(self)
        keys: set[str] = set()
        for child in self.children:
            if child.id in keys:
                raise IrValidationError("duplicate child key", node_id=id, key=child.id)
            keys.add(child.id)
