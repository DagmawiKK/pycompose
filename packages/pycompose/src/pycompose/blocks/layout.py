"""The declaration: elements, the layouts that hold them, and their events.

An element joins the layout open around it when it is created, so the order of
the code is the order on screen::

    with Row():
        name = Textbox(label="Name")
        Button("Greet")

Ids are given once the screen is complete, in that order, so the same code names
the same elements on every run, a reload included.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Self, TypeVar

from pycompose.errors import StateError

if TYPE_CHECKING:
    from pycompose.blocks.components import Component
    from pycompose.blocks.screen import View
    from pycompose.core.node import Node

__all__ = ["Container", "Element", "Event", "detached"]

Trigger = Literal["change", "click"]
T = TypeVar("T")

_OPEN: ContextVar[tuple[Container, ...]] = ContextVar(
    "pycompose_blocks_open", default=()
)


@dataclass(frozen=True)
class Event:
    """A function an element runs when it fires, and where its result goes.

    Attributes:
        trigger: What fires it.
        fn: Called with the inputs' values, in order. A coroutine function is
            awaited on the loop, any other runs on the I/O pool; one that
            yields streams each value it yields into the outputs.
        inputs: The components whose values ``fn`` receives.
        outputs: The components ``fn``'s result is written to: one value per
            output, a tuple for several.
    """

    trigger: Trigger
    fn: Callable[..., Any]
    inputs: tuple[Component, ...]
    outputs: tuple[Component, ...]


def _components(value: Component | Sequence[Component] | None) -> tuple[Component, ...]:
    if value is None:
        return ()
    if isinstance(value, Sequence):
        return tuple(value)
    return (value,)


class Element:
    """Something on the screen; it joins the layout open around it.

    Args:
        visible: Whether it is drawn.
    """

    def __init__(self, *, visible: bool = True) -> None:
        self.visible = visible
        self.id = ""
        self.events: list[Event] = []
        self.parent: Container | None = None
        opened = _OPEN.get()
        if opened:
            opened[-1].add(self)

    def listen(
        self,
        trigger: Trigger,
        fn: Callable[..., Any],
        inputs: Component | Sequence[Component] | None,
        outputs: Component | Sequence[Component] | None,
    ) -> Event:
        """Run ``fn`` whenever this element fires ``trigger``.

        Args:
            trigger: What fires it.
            fn: The function; see :class:`Event`.
            inputs: The components it reads.
            outputs: The components it writes.

        Returns:
            The event.
        """
        event = Event(trigger, fn, _components(inputs), _components(outputs))
        self.events.append(event)
        return event

    def walk(self) -> Iterator[Element]:
        """Yield this element and everything inside it, in screen order.

        Yields:
            Element: Each element.
        """
        yield self

    def draw(self, view: View) -> Node:
        """Return this element's native nodes for the state the view holds.

        Args:
            view: The state being drawn.

        Returns:
            Its nodes.

        Raises:
            NotImplementedError: Unless a subclass draws itself.
        """
        raise NotImplementedError


class Container(Element):
    """An element holding others; open it with ``with`` to fill it."""

    def __init__(self, *, visible: bool = True) -> None:
        super().__init__(visible=visible)
        self.children: list[Element] = []

    def add(self, *elements: Element) -> None:
        """Place elements at the end of this layout.

        Args:
            *elements: Elements not yet placed.

        Raises:
            StateError: If one is already placed.
        """
        for element in elements:
            if element.parent is not None:
                raise StateError("an element is placed once")
            element.parent = self
            self.children.append(element)

    def walk(self) -> Iterator[Element]:
        """Yield this layout and everything inside it, in screen order.

        Yields:
            Element: Each element.
        """
        yield self
        for child in self.children:
            yield from child.walk()

    def __enter__(self) -> Self:
        _OPEN.set((*_OPEN.get(), self))
        return self

    def __exit__(self, *_exc: object) -> None:
        _OPEN.set(_OPEN.get()[:-1])


def detached(build: Callable[[], T]) -> T:
    """Build an element that joins no open layout.

    Args:
        build: Builds it.

    Returns:
        What ``build`` returned.
    """
    token = _OPEN.set(())
    try:
        return build()
    finally:
        _OPEN.reset(token)
