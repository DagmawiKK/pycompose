"""A lazy container declared over data, composed one window at a time."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from types import MappingProxyType
from typing import Any

from pycompose.core.expansion import DeferredNode, building_path
from pycompose.core.node import Node
from pycompose.core.windows import window_for
from pycompose.errors import IrValidationError


class Windowed(DeferredNode):
    """``LazyColumn(items=notes, key=..., item=...)``: a list as data, not nodes.

    It states the item count, composes only the items in the window the host
    asked for, and keys each by ``key``, so a 10,000-item list costs what is on
    screen. It is built on every pass, since the window is not one of its
    inputs; the items it builds are ordinary declarations and reuse as usual.
    """

    __slots__ = ("component", "data", "item", "keyed", "options")
    memoized = False

    component: Callable[..., Node]
    data: tuple[object, ...]
    keyed: Callable[[Any], str | int]
    item: Callable[[Any], Node]
    options: Mapping[str, object]

    def __init__(
        self,
        component: Callable[..., Node],
        *,
        site: str,
        id: str | None,
        items: Sequence[object],
        key: Callable[[Any], str | int] | None,
        item: Callable[[Any], Node],
        **props: object,
    ) -> None:
        """Declare a windowed container.

        Args:
            component: The lazy container's class.
            site: The call site declaring it, when it has no id.
            id: Stable instance key, or None to key it by its call site.
            items: The data, in order.
            key: Each item's stable key.
            item: Builds one item's node.
            **props: The container's own props.

        Raises:
            IrValidationError: If no key was given; items told apart only by
                position would swap state on every insertion.
        """
        if key is None:
            raise IrValidationError("a windowed list needs key= with item=", node_id=id)
        super().__init__(id=id or "", type="@window", site="" if id else site)
        object.__setattr__(self, "component", component)
        object.__setattr__(self, "data", tuple(items))
        object.__setattr__(self, "keyed", key)
        object.__setattr__(self, "item", item)
        object.__setattr__(self, "options", MappingProxyType(dict(props)))

    @property
    def recursion_key(self) -> object:
        return (type(self), id(self))

    @property
    def source(self) -> str:
        return f"windowed {getattr(self.component, '__name__', 'list')}"

    def build(self) -> tuple[Node, ...]:
        key = f"{building_path()}/{self.id or self.site}"
        window = window_for(key, len(self.data))
        children = [
            self.item(entry).with_id(str(self.keyed(entry)))
            for entry in self.data[window.start : window.stop]
        ]
        built = self.component(children=children, **self.options)
        props: dict[str, Any] = dict(built.props.values)
        props.update(itemCount=len(self.data), itemOffset=window.start, window=key)
        return (
            Node(
                id=self.id,
                type=built.type,
                props=props,
                children=built.children,
                slot=self.slot,
                site=self.site,
            ),
        )
