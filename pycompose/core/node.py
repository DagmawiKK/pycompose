"""Frozen IR node and its immutable prop bag (pure, stdlib-only).

A :class:`Node` is the unit of the IR tree: a stable id, a component type,
``camelCase`` props, and children. Both are frozen so a snapshot is a value.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import cast

from pycompose.core.props import JsonValue, is_camel_case
from pycompose.errors import IrError
from pycompose.utils.json_canonical import FrozenJsonValue, freeze_json, thaw_json

__all__ = ["Node", "Props"]


@dataclass(frozen=True, slots=True)
class Props:
    """Immutable, validated ``camelCase`` prop bag for a :class:`Node`.

    Attributes:
        values: The ``camelCase`` prop values; frozen to a read-only mapping.
    """

    values: Mapping[str, JsonValue | FrozenJsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Freeze the mapping and reject non-``camelCase`` prop names.

        Raises:
            IrError: If any prop name is not ``camelCase``.
        """
        frozen = cast(Mapping[str, FrozenJsonValue], freeze_json(self.values))
        for name in frozen:
            if not is_camel_case(name):
                raise IrError("prop name is not camelCase", prop=name)
        object.__setattr__(self, "values", frozen)

    def __getitem__(self, name: str) -> JsonValue | FrozenJsonValue:
        """Return the prop named ``name``.

        Args:
            name: The ``camelCase`` prop name.

        Returns:
            The prop value.
        """
        return self.values[name]

    def __iter__(self) -> Iterator[str]:
        """Iterate over prop names.

        Returns:
            An iterator over the prop names.
        """
        return iter(self.values)

    def __len__(self) -> int:
        """Return the number of props.

        Returns:
            The prop count.
        """
        return len(self.values)

    def __contains__(self, name: object) -> bool:
        """Report whether ``name`` is present.

        Args:
            name: The candidate prop name.

        Returns:
            ``True`` when the prop is present.
        """
        return name in self.values

    def get(self, name: str, default: JsonValue = None) -> JsonValue | FrozenJsonValue:
        """Return ``name`` or ``default`` when absent.

        Args:
            name: The prop name.
            default: Value returned when the prop is absent.

        Returns:
            The prop value or ``default``.
        """
        return self.values.get(name, default)

    def to_wire(self) -> dict[str, JsonValue]:
        """Return a plain ``camelCase`` mapping of the prop values.

        Returns:
            A detached JSON copy of the prop values.
        """
        return {name: thaw_json(value) for name, value in self.values.items()}


_EMPTY_PROPS = Props()


@dataclass(frozen=True, slots=True, init=False)
class Node:
    """One immutable element of the IR tree.

    Attributes:
        id: Stable, parent-path-derived node id.
        type: Component type name (e.g. ``Button``).
        props: The node's ``camelCase`` props.
        children: Child nodes (empty for leaves).
    """

    id: str
    type: str
    props: Props = field(default_factory=Props)
    children: tuple[Node, ...] = ()

    def __init__(
        self,
        id: str,
        type: str,
        props: Props | Mapping[str, JsonValue | FrozenJsonValue] = _EMPTY_PROPS,
        children: Iterable[Node] = (),
    ) -> None:
        """Construct a node, normalizing mappings into immutable Props.

        Invalid structural fields propagate IrError from normalization.

        Args:
            id: Stable node id.
            type: Registered component name (validated later).
            props: Immutable Props or caller-owned mapping to detach.
            children: Child nodes, normalized to a tuple.
        """
        object.__setattr__(self, "id", id)
        object.__setattr__(self, "type", type)
        object.__setattr__(self, "props", props)
        object.__setattr__(self, "children", children)
        self.__post_init__()

    def __post_init__(self) -> None:
        """Validate structure and detach raw props at the ownership boundary.

        Raises:
            IrError: If identity, props or child types are invalid.
        """
        if not isinstance(self.id, str) or not self.id:
            raise IrError("node id must be non-empty", node_type=self.type)
        if not isinstance(self.type, str) or not self.type:
            raise IrError("node type must be non-empty", node_id=self.id)
        props = cast(object, self.props)
        if not isinstance(props, Props):
            if not isinstance(props, Mapping):
                raise IrError("node props must be a mapping", node_id=self.id)
            object.__setattr__(self, "props", Props(props))
        try:
            children = tuple(self.children)
        except TypeError as exc:
            raise IrError("node children must be iterable", node_id=self.id) from exc
        if any(not isinstance(child, Node) for child in children):
            raise IrError("node children must be Nodes", node_id=self.id)
        object.__setattr__(self, "children", children)
