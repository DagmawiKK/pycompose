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


def _slot_names(cls: type) -> Iterator[str]:
    """Yield every slotted attribute declared in ``cls``'s ancestry.

    Args:
        cls: A node class.

    Yields:
        str: Slot names, base classes first.
    """
    for base in reversed(cls.__mro__):
        declared = getattr(base, "__slots__", ())
        yield from (declared,) if isinstance(declared, str) else declared


@dataclass(frozen=True, slots=True, init=False)
class Node:
    """One immutable element of the IR tree.

    Attributes:
        id: Stable, parent-path-derived node id.
        type: Component type name (e.g. ``Button``).
        props: The node's ``camelCase`` props.
        children: Child nodes (empty for leaves).
        slot: Named slot this node fills in its parent, or ``None`` for the
            parent's primary children.
        site: The line of code that declared a node with no id, which keys it
            among its siblings; empty for nodes built outside a declaration.
    """

    id: str
    type: str
    props: Props = field(default_factory=Props)
    children: tuple[Node, ...] = ()
    slot: str | None = None
    site: str = ""

    def __init__(
        self,
        id: str,
        type: str,
        props: Props | Mapping[str, JsonValue | FrozenJsonValue] = _EMPTY_PROPS,
        children: Iterable[Node] = (),
        slot: str | None = None,
        site: str = "",
    ) -> None:
        """Construct a node, normalizing mappings into immutable Props.

        Invalid structural fields propagate IrError from normalization.

        Args:
            id: Stable node id.
            type: Registered component name (validated later).
            props: Immutable Props or caller-owned mapping to detach.
            children: Child nodes, normalized to a tuple.
            slot: Named slot in the parent, or ``None`` for primary children.
            site: Declaring call site, the sibling key of a node with no id.
        """
        object.__setattr__(self, "id", id)
        object.__setattr__(self, "type", type)
        object.__setattr__(self, "props", props)
        object.__setattr__(self, "children", children)
        object.__setattr__(self, "slot", slot)
        object.__setattr__(self, "site", site)
        self.__post_init__()

    def __post_init__(self) -> None:
        """Validate structure and detach raw props at the ownership boundary.

        Raises:
            IrError: If identity, props, slot or child types are invalid.
        """
        if not isinstance(self.id, str):
            raise IrError("node id must be a string", node_type=self.type)
        if not isinstance(self.type, str) or not self.type:
            raise IrError("node type must be non-empty", node_id=self.id)
        if self.slot is not None and (
            not isinstance(self.slot, str) or not is_camel_case(self.slot)
        ):
            raise IrError("node slot must be a camelCase name", node_id=self.id)
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

    def with_slot(self, slot: str) -> Node:
        """Return this node filling ``slot`` in its parent.

        The copy keeps the concrete class, so a deferred composition stays
        deferred and is expanded where it sits rather than flattening into an
        unbuildable node. Ids stay unique because a node never belongs to two
        slots.

        Args:
            slot: Declared ``camelCase`` slot name.

        Returns:
            A node equal to this one apart from its slot.

        Raises:
            IrError: If ``slot`` is not a ``camelCase`` name.
        """
        if not isinstance(slot, str) or not is_camel_case(slot):
            raise IrError("node slot must be a camelCase name", node_id=self.id)
        if slot == self.slot:
            return self
        marked = object.__new__(type(self))
        for name in _slot_names(type(self)):
            object.__setattr__(marked, name, getattr(self, name))
        object.__setattr__(marked, "slot", slot)
        return marked
