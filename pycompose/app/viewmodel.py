"""ViewModel: one screen's state, its intents and its supervised work."""

from __future__ import annotations

import contextvars
import threading
from collections.abc import Callable, Coroutine, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from pycompose.app.effects import TypedEffect
from pycompose.app.intents import Intent
from pycompose.core.effect import Effect
from pycompose.errors import StateError
from pycompose.runtime.scope import Report, Scope
from pycompose.state.app_state import AppState

__all__ = ["ViewModel", "ViewModelHost", "hosting"]

S = TypeVar("S", bound=AppState)


@dataclass(frozen=True)
class ViewModelHost:
    """What the session gives each view model it builds.

    Attributes:
        report: Receives each supervised task's failure.
        changed: Called when state changes outside an intent, so the session
            publishes it.
    """

    report: Report
    changed: Callable[[], None]


_HOST: contextvars.ContextVar[ViewModelHost | None] = contextvars.ContextVar(
    "pycompose_view_model_host", default=None
)


@contextmanager
def hosting(host: ViewModelHost) -> Iterator[None]:
    """Give every view model built inside the block this host.

    Args:
        host: The session's host for its view models.
    """
    token = _HOST.set(host)
    try:
        yield
    finally:
        _HOST.reset(token)


class ViewModel(Generic[S]):
    """One screen's state and behaviour.

    Its state is read and written only on the thread that built it, the session's
    loop thread, so assigning ``self.state`` needs no lock. Intents arrive through
    :meth:`on_intent`; work runs in tasks started with :meth:`launch`, which a
    failure in one never cancels another, and which all end when the view model
    is cleared.

    Args:
        state: The screen's first state.
    """

    def __init__(self, state: S) -> None:
        self._state = state
        self._owner = threading.current_thread()
        self._host = _HOST.get()
        self._effects: list[Effect] = []
        self._scope = (
            Scope(type(self).__qualname__, self._host.report) if self._host else None
        )

    @property
    def state(self) -> S:
        """The screen's current state.

        Returns:
            The state its screen renders.
        """
        return self._state

    @state.setter
    def state(self, state: S) -> None:
        if threading.current_thread() is not self._owner:
            raise StateError(
                "a view model's state changes only on its own thread; return the "
                "value from the worker thread and assign it after the await"
            )
        self._state = state
        if self._host is not None:
            self._host.changed()

    def emit(self, effect: TypedEffect) -> None:
        """Ask the host for a one-shot effect with the next snapshot.

        Args:
            effect: The effect to run.
        """
        self._effects.append(effect.effect())
        if self._host is not None:
            self._host.changed()

    def launch(self, work: Coroutine[Any, Any, Any]) -> None:
        """Run ``work`` until it ends or this view model is cleared.

        Args:
            work: The coroutine to run.

        Raises:
            StateError: If the view model was built outside a session.
        """
        if self._scope is None:
            work.close()
            raise StateError("launch needs a view model built by a session")
        self._scope.spawn(work)

    def on_intent(self, intent: Intent) -> None:
        """Handle one intent from the screen.

        Args:
            intent: What the control asked for.

        Raises:
            NotImplementedError: Unless a subclass handles intents.
        """
        raise NotImplementedError(f"{type(self).__name__} handles no intents")

    def on_cleared(self) -> None:
        """Release what the view model holds; its tasks are already cancelled."""

    async def clear(self) -> None:
        """Cancel every task, then call :meth:`on_cleared`."""
        if self._scope is not None:
            await self._scope.close()
        self.on_cleared()

    def take_effects(self) -> tuple[Effect, ...]:
        """Return and forget the effects emitted since the last snapshot.

        Returns:
            The effects, in the order they were emitted.
        """
        effects, self._effects = tuple(self._effects), []
        return effects
