"""The app's declared entry: the shell, the view and the long-lived objects.

The session finds one :class:`App` in the entry module and runs it. There is no
``build`` or ``container`` to export under a blessed name: everything the
session needs hangs off this one object.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Generic, TypeVar, cast

from pycompose.core.node import Node
from pycompose.errors import StateError
from pycompose.state.app_state import AppState
from pycompose.state.state import State

__all__ = ["App"]

S = TypeVar("S", bound=AppState)


class App(Generic[S]):
    """What the session discovers in the entry module, and everything it runs.

    Two shapes share this object:

    * A **shell app** declares ``state``, a seed of its :class:`AppState`
      shell. The view receives that shell and returns the screen, and the
      session owns the restore dance: the host's bytes are decoded through the
      shell's own codec, and a save that is unreadable or unreadable-as-this-app
      falls back to the seed, so a corrupt save leaves a working app.
    * A **data app** declares no shell. Its view receives the host's saved
      bytes directly and returns the first :class:`State`, so an app whose
      state is ordinary JSON keeps owning its own rehydration.
    """

    def __init__(
        self,
        *,
        state: Callable[[], S] | None = None,
        view: Callable[..., Node | State],
        container: Callable[[], object] | None = None,
        route: str | None = None,
    ) -> None:
        """Validate the declared entry once, so a misspelling fails at import.

        Args:
            state: Seed of the app's shell, normally the shell class itself.
            view: The shell renderer, or the whole first snapshot for a data app.
            container: Factory of the app's long-lived objects. The session
                calls it exactly once per process and retains the result across
                debug reloads; None when the app declares none.
            route: Name of the shell field mirroring the host's restored route.
                The host's route wins over the one recorded in a save, so it is
                applied here on every build. None means the app keeps no route
                field and decides its own screen.

        Raises:
            StateError: If any declared piece is not callable, or the route
                field name is not a non-empty string.
        """
        if state is not None and not callable(state):
            raise StateError("app state must be a zero-argument shell seed")
        if not callable(view):
            raise StateError("app view must be callable")
        if container is not None and not callable(container):
            raise StateError("app container must be a zero-argument callable")
        if route is not None and (not isinstance(route, str) or not route):
            raise StateError("route must be a non-empty field name or None")
        self._state = state
        self._view = view
        self.container = container
        self.route = route

    @property
    def session_view(self) -> Callable[[S], Node] | None:
        """Return the shell renderer, for session-native actions.

        Returns:
            The view when this app declares a shell, else None. The session
            installs it on the registry so a session-native action can rebuild
            its screen after a transition.
        """
        if self._state is None:
            return None
        return cast("Callable[[S], Node]", self._view)

    def build(self, *, route: str, restore: str = "") -> State:
        """Return the first snapshot for a freshly started process.

        Args:
            route: The route the host restored from its own saved state.
            restore: Canonical JSON this app published previously, or empty on
                a first run. Only the host's own bytes are ever handed back.

        Returns:
            The first snapshot for the requested route.

        Raises:
            StateError: If the shell seed is unusable.
        """
        if self._state is None:
            result = self._view(restore)
            if not isinstance(result, State):
                raise StateError("a data app's view must return State")
            return result
        seed = self._state()
        if not isinstance(seed, AppState):
            raise StateError("app state seed must produce an AppState shell")
        shell = self._rehydrated(restore, seed)
        if self.route is not None:
            shell = shell.evolve(**{self.route: route})
        return State(
            root=cast("Node", self._view(shell)),
            version=0,
            app=shell,
        )

    def _rehydrated(self, restore: str, seed: S) -> S:
        """Return the shell the host's saved bytes describe.

        Args:
            restore: Canonical JSON from a previous snapshot, or empty on a
                first run.
            seed: The shell a fresh install starts from.

        Returns:
            The restored shell, or the seed when the bytes are unusable. A
            corrupt save leaves a working app rather than a crash.
        """
        if not restore:
            return seed
        try:
            decoded = json.loads(restore)
            return cast("S", type(seed).codec.decode(decoded))
        except (StateError, ValueError):
            # Siblings, not parent and child: the parse raises ValueError and
            # the codec raises StateError, and a save that is either unreadable
            # or unreadable-as-this-app is the same problem to the user.
            return seed
