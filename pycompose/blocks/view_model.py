"""The view model behind every blocks screen: values in, functions run, results out."""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Mapping
from dataclasses import field
from typing import Any

from pycompose.app.effects import Toast
from pycompose.app.intents import Intent
from pycompose.app.viewmodel import ViewModel
from pycompose.blocks.components import Component
from pycompose.blocks.intents import Expand, Fire, SetFlag, SetNumber, SetText
from pycompose.blocks.layout import Element, Event, Trigger
from pycompose.runtime.scheduler import to_thread
from pycompose.state import AppState, Loaded

__all__ = ["BlocksState", "BlocksViewModel"]

LOGGER = logging.getLogger(__name__)


class BlocksState(AppState):
    """What a blocks screen shows.

    Attributes:
        values: Each component's value, by id, once the user or an event set
            it; a component not here shows its first value.
        expanded: Each menu and section opened or closed, by id.
        busy: The outputs of events still running; never saved, since the
            work does not survive the process.
    """

    values: dict[str, Any] = field(default_factory=dict)
    expanded: dict[str, bool] = field(default_factory=dict)
    busy: Loaded[frozenset[str]] = frozenset()


class BlocksViewModel(ViewModel[BlocksState]):
    """Runs a blocks screen's events.

    An event that fires again before its last run returned supersedes it: the
    last run is cancelled, so only the latest result is ever shown.

    Args:
        elements: Every element on the screen, by id.
    """

    def __init__(self, elements: Mapping[str, Element]) -> None:
        super().__init__(BlocksState())
        self._elements = elements
        self._runs: dict[Event, asyncio.Task[None]] = {}

    def on_intent(self, intent: Intent) -> None:
        """Apply what a control reported, then run what listens to it.

        Args:
            intent: The control's report.
        """
        match intent:
            case (
                SetText(component=key, value=value)
                | SetNumber(component=key, value=value)
                | SetFlag(component=key, value=value)
            ):
                self._changed(key, value)
            case Expand(component=key, expanded=expanded):
                self.state = self.state.evolve(
                    expanded={**self.state.expanded, key: expanded}
                )
            case Fire(component=key):
                self._fire(key, "click")

    def _changed(self, key: str, value: Any) -> None:
        if key not in self._elements:
            return  # drawn by code a reload has since replaced
        expanded = {k: v for k, v in self.state.expanded.items() if k != key}
        # Choosing from a menu closes it.
        self.state = self.state.evolve(
            values={**self.state.values, key: value}, expanded=expanded
        )
        self._fire(key, "change")

    def _fire(self, key: str, trigger: Trigger) -> None:
        element = self._elements.get(key)
        for event in element.events if element is not None else ():
            if event.trigger == trigger:
                self._start(event)

    def _start(self, event: Event) -> None:
        previous = self._runs.pop(event, None)
        if previous is not None:
            previous.cancel()
        try:
            args = [c.to_python(self._value(c)) for c in event.inputs]
        except Exception as error:  # an input the user left unreadable
            self.emit(Toast(message=str(error)))
            return
        outputs = {c.id for c in event.outputs}
        self.state = self.state.evolve(busy=self.state.busy | outputs)
        self._runs[event] = self.launch(self._run(event, args))

    async def _run(self, event: Event, args: list[Any]) -> None:
        try:
            if inspect.iscoroutinefunction(event.fn):
                result = await event.fn(*args)
            else:
                result = await to_thread("io", event.fn, *args)
            written = _written(event.outputs, result)
        except asyncio.CancelledError:
            raise  # superseded: the newer run owns the outputs now
        except Exception as error:
            LOGGER.warning("%s failed", event.fn.__qualname__, exc_info=True)
            self.emit(Toast(message=str(error) or type(error).__name__))
            written = {}
        if self._runs.get(event) is not asyncio.current_task():
            return
        del self._runs[event]
        self.state = self.state.evolve(
            values={**self.state.values, **written},
            busy=self.state.busy - {c.id for c in event.outputs},
        )

    def _value(self, component: Component) -> Any:
        return self.state.values.get(component.id, component.default)


def _written(outputs: tuple[Component, ...], result: Any) -> dict[str, Any]:
    """Pair a function's result with its outputs, as the outputs hold values.

    Args:
        outputs: The event's outputs.
        result: What the function returned.

    Returns:
        Each output's new value, by id.

    Raises:
        ValueError: If the result does not give one value per output.
    """
    if not outputs:
        return {}
    if len(outputs) == 1:
        return {outputs[0].id: outputs[0].to_raw(result)}
    if not isinstance(result, tuple | list) or len(result) != len(outputs):
        raise ValueError(f"expected {len(outputs)} results, one per output")
    return {c.id: c.to_raw(value) for c, value in zip(outputs, result, strict=True)}
