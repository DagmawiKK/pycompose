"""A blocks app: a screen declared in a ``with`` block, run as an ordinary app."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any, Self

from pycompose.app.app import App, Destination
from pycompose.app.observe import Failure, Span
from pycompose.blocks.components import Button, Component
from pycompose.blocks.containers import Column
from pycompose.blocks.layout import Element, detached
from pycompose.blocks.screen import View
from pycompose.blocks.view_model import BlocksState, BlocksViewModel
from pycompose.m3 import Column as NativeColumn
from pycompose.m3 import Modifier

if TYPE_CHECKING:
    from pycompose.core.node import Node

__all__ = ["Blocks", "Interface"]


class Blocks(App):
    """An app whose one screen is declared inside ``with``.

    Every component and layout created in the block joins the screen in order.
    The result is an :class:`~pycompose.app.App`: it runs, reloads, saves and
    restores like any other, on one :class:`BlocksViewModel`.

    Args:
        on_error: Receives every supervised failure, as for any app.
        exporter: Receives one span per pass, as for any app.

    Attributes:
        root: The layout every element created in the block joins.
    """

    # Compared and hashed by identity: its destination refers back to it.
    __eq__ = object.__eq__
    __hash__ = object.__hash__

    def __init__(
        self,
        *,
        on_error: Callable[[Failure], None] | None = None,
        exporter: Callable[[Span], None] | None = None,
    ) -> None:
        object.__setattr__(self, "root", detached(Column))
        object.__setattr__(self, "_index", None)
        super().__init__(
            start=Destination(
                lambda _container, _route: self._view_model(), self._screen
            ),
            on_error=on_error,
            exporter=exporter,
        )

    root: Column
    _index: tuple[dict[str, Element], frozenset[str]] | None

    def __enter__(self) -> Self:
        self.root.__enter__()
        return self

    def __exit__(self, *exc: object) -> None:
        self.root.__exit__(*exc)

    def _elements(self) -> tuple[dict[str, Element], frozenset[str]]:
        """Name every element in screen order, once the screen is complete."""
        if self._index is not None:
            return self._index
        elements: dict[str, Element] = {}
        for number, element in enumerate(self.root.walk()):
            element.id = f"b{number}"
            elements[element.id] = element
        outputs = frozenset(
            c.id for e in elements.values() for ev in e.events for c in ev.outputs
        )
        object.__setattr__(self, "_index", (elements, outputs))
        return elements, outputs

    def _view_model(self) -> BlocksViewModel:
        return BlocksViewModel(self._elements()[0])

    def _screen(self, state: BlocksState) -> Node:
        _, outputs = self._elements()
        view = View(state, outputs)
        return NativeColumn(
            scrollable=True,
            modifier=Modifier().fill_max_width().padding(16),
            children=[self.root.draw(view)],
        )


def Interface(  # noqa: N802 -- reads as the class of app it builds
    fn: Callable[..., Any],
    inputs: Component | Sequence[Component],
    outputs: Component | Sequence[Component],
    *,
    submit: str = "Submit",
) -> Blocks:
    """Build the usual app around one function: inputs, a button, outputs.

    Args:
        fn: Called with the inputs' values; its result fills the outputs.
        inputs: The components it reads, stacked above the button.
        outputs: The components it writes, stacked below.
        submit: What the button says.

    Returns:
        The app.
    """
    ins = tuple(inputs) if isinstance(inputs, Sequence) else (inputs,)
    outs = tuple(outputs) if isinstance(outputs, Sequence) else (outputs,)
    with Blocks() as app:
        app.root.add(*ins)
        Button(submit).click(fn, ins, outs)
        app.root.add(*outs)
    return app
