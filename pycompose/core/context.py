"""The app context a composition can reach without it being threaded through.

Compose has this: ``LocalConfiguration.current`` answers what a composable's
device configuration is without anyone passing it in, and
``CompositionLocalProvider`` is how you put something there. PyCompose needs the
same thing for the same reason, and for no other reason.

It is a module global, and that is a deliberate echo of a design that was
deleted two commits ago. The difference matters: the service locator held *the
app's dependencies* and let any function fish them out by name, so a unit test
could not run a handler alone. This holds *what a composition is allowed to
reach* -- the registry a screen binds through, and the container a render
function re-reads. Those are the two things every screen would otherwise be
handed, and handing them is what made every signature carry a parameter nobody
could drop.

The line it draws is narrow on purpose. Anything that **mutates** storage still
takes ``container`` as an explicit parameter. Ambient access is for the render
path; the domain path stays visible.
"""

from __future__ import annotations

import threading
from typing import Any

__all__ = ["AppContext", "context", "has_context", "install"]

_lock = threading.RLock()
_current: AppContext | None = None


class AppContext:
    """What a composition may reach without it being passed in.

    Attributes are untyped on purpose: this module sits below every layer that
    could name a real type, and duck typing is what keeps the boundary honest
    rather than an import cycle in disguise.
    """

    def __init__(self, **values: Any) -> None:
        """Hold the values a composition may reach.

        Args:
            **values: Named values, such as ``actions`` or ``container``.
        """
        self._values = dict(values)

    def get(self, name: str) -> Any:
        """Return one of this context's values.

        Args:
            name: What to look for.

        Returns:
            The value, or None when this context does not carry it.
        """
        return self._values.get(name)

    def __contains__(self, name: object) -> bool:
        """Report whether this context carries a value.

        Args:
            name: What to look for.

        Returns:
            True when it does.
        """
        return name in self._values

    def __getattr__(self, name: str) -> Any:
        """Return one of this context's values by attribute.

        Args:
            name: What to look for.

        Returns:
            The value.

        Raises:
            AttributeError: If this context does not carry it.
        """
        try:
            return self._values[name]
        except KeyError:
            raise AttributeError(
                f"the app context carries no {name!r}; it holds "
                f"{', '.join(sorted(self._values)) or 'nothing'}"
            ) from None


def install(context: AppContext | None) -> None:
    """Make a context the one compositions resolve against.

    Args:
        context: The context, or None to remove the one in place.
    """
    global _current  # noqa: PLW0603 -- one per session, deliberately
    with _lock:
        _current = context


def has_context() -> bool:
    """Report whether a context is installed.

    Returns:
        True when one is.
    """
    return _current is not None


def context() -> AppContext:
    """Return the context compositions resolve against.

    Returns:
        The installed context.

    Raises:
        KeyError: If no session has installed one. Reaching this from app code
            means a composable or render function was called outside a session,
            which is the situation the message exists to name.
    """
    if _current is None:
        raise KeyError(
            "no app context is installed; a composition was reached outside a "
            "session. The session installs one when it starts."
        )
    return _current
