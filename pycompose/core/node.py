"""Frozen IR node and its immutable prop bag (pure, stdlib-only).

A :class:`Node` is the unit of the IR tree: a stable id, a component type,
``camelCase`` props, and children. Both are frozen so a snapshot is a value.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from pycompose.core.props import JsonValue, is_camel_case
from pycompose.errors import IrError

__all__ = ["Node", "Props"]


@dataclass(frozen=True, slots=True)
class Props:
    """Immutable, validated ``camelCase`` prop bag for a :class:`Node`.

    Attributes:
        values: The ``camelCase`` prop values; frozen to a read-only mapping.
    """

    values: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Freeze the mapping and reject non-``camelCase`` prop names.

        Raises:
            IrError: If any prop name is not ``camelCase``.
        """
        frozen: Mapping[str, JsonValue] = MappingProxyType(dict(self.values))
        for name in frozen:
            if not is_camel_case(name):
                raise IrError("prop name is not camelCase", prop=name)
        object.__setattr__(self, "values", frozen)

    def __getitem__(self, name: str) -> JsonValue:
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

    def get(self, name: str, default: JsonValue = None) -> JsonValue:
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
            A shallow copy of the prop values.
        """
        return dict(self.values)


@dataclass(frozen=True, slots=True)
class Node:
    """One immutable element of the IR tree.

    Attributes:
        id: Stable, parent-path-derived node id.
        type: Component type name (e.g. ``FilledButton``).
        props: The node's ``camelCase`` props.
        children: Child nodes (empty for leaves).
    """

    id: str
    type: str
    props: Props = field(default_factory=Props)
    children: tuple[Node, ...] = ()

    def __post_init__(self) -> None:
        """Validate identity and normalize ``children`` to a tuple.

        Raises:
            IrError: If ``id`` or ``type`` is empty.
        """
        if not self.id:
            raise IrError("node id must be non-empty", node_type=self.type)
        if not self.type:
            raise IrError("node type must be non-empty", node_id=self.id)
        object.__setattr__(self, "children", tuple(self.children))
