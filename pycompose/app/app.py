"""The app: its container and the destination it starts on."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from pycompose.app.viewmodel import ViewModel
from pycompose.core.node import Node
from pycompose.state.app_state import AppState

__all__ = ["App", "Destination"]

S = TypeVar("S", bound=AppState)


@dataclass(frozen=True)
class Destination(Generic[S]):
    """One screen: how to build its view model, and how to draw its state.

    Attributes:
        view_model: Builds the view model from the app's container (Google's
            manual dependency injection), or from nothing without one.
        screen: Draws the view model's state; a pure function of it.
    """

    view_model: Callable[..., ViewModel[S]]
    screen: Callable[[S], Node]


@dataclass(frozen=True)
class App:
    """A PyCompose app built from view models.

    Attributes:
        start: The destination the app opens on.
        container: Builds the app's long-lived objects once per session, or
            None for an app with none.
    """

    start: Destination[Any]
    container: Callable[[], object] | None = None
