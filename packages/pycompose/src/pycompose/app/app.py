"""The app: its container, its destinations and where it starts."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from pycompose.app.navigation import Route
from pycompose.app.observe import Failure, Span
from pycompose.app.viewmodel import ViewModel
from pycompose.core.node import Node
from pycompose.errors import StateError
from pycompose.state.app_state import AppState

__all__ = ["App", "Destination", "Home"]

S = TypeVar("S", bound=AppState)


@dataclass(frozen=True)
class Destination(Generic[S]):
    """One screen: how to build its view model, and how to draw its state.

    Attributes:
        view_model: Builds the view model from the app's container (Google's
            manual dependency injection; None without one) and the route that
            opened it.
        screen: Draws the view model's state; a pure function of it.
    """

    view_model: Callable[[Any, Any], ViewModel[S]]
    screen: Callable[[S], Node]


class Home(Route):
    """The route of an app with a single destination."""


@dataclass(frozen=True)
class App:
    """A PyCompose app built from view models.

    Attributes:
        start: The route the app opens on, or the destination of an app with
            only one screen.
        destinations: The destination each route class opens.
        container: Builds the app's long-lived objects once per session, or
            None for an app with none.
        deep_links: Route classes the host may open from outside the app; any
            other route it names is ignored.
        on_error: Receives every supervised failure -- a view model's work or
            an intent's handler -- with the trace id of the input behind it,
            for a crash service. It runs on the loop thread; a failure in it is
            logged and goes no further.
        exporter: Receives one span per pass, for a tracing backend; none is
            shipped. It runs on the loop thread, so it should hand off quickly.
    """

    start: Route | Destination[Any]
    destinations: Mapping[type[Route], Destination[Any]] = field(default_factory=dict)
    container: Callable[[], object] | None = None
    deep_links: frozenset[type[Route]] = frozenset()
    on_error: Callable[[Failure], None] | None = None
    exporter: Callable[[Span], None] | None = None

    def __post_init__(self) -> None:
        if self.container is not None and not callable(self.container):
            raise StateError("an app's container must be a zero-argument callable")

    def route(self) -> Route:
        """Return the route the app starts on.

        Returns:
            The start route.
        """
        return Home() if isinstance(self.start, Destination) else self.start

    def destination(self, route: Route) -> Destination[Any]:
        """Return the destination a route opens.

        Args:
            route: The route.

        Returns:
            Its destination.

        Raises:
            StateError: If no destination is declared for the route's class.
        """
        if isinstance(self.start, Destination) and isinstance(route, Home):
            return self.start
        destination = self.destinations.get(type(route))
        if destination is None:
            raise StateError("no destination for route", route=type(route).__name__)
        return destination
