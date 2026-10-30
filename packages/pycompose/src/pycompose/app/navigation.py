"""Typed routes and the operations that change the back stack.

A route is a frozen dataclass naming a destination and its arguments, such as
``EditorRoute(id=4)``. It travels to the host as canonical JSON, which the host
keeps only to hand back after process death; what a route means is the app's.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from pycompose.errors import StateError
from pycompose.model.canonical import canonical_json
from pycompose.state.app_state import AppState

__all__ = ["Pop", "Push", "Replace", "Route", "parse_route", "route_key"]

_ROUTES: dict[str, type[Route]] = {}


class Route(AppState):
    """Base for a destination and its arguments."""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # A reload defines the class again; the newest wins.
        _ROUTES[_name(cls)] = cls


def _name(cls: type) -> str:
    return f"{cls.__module__}.{cls.__qualname__}"


def route_key(route: Route) -> str:
    """Return the string a route travels as: its canonical JSON.

    Args:
        route: The route.

    Returns:
        ``{"fields": ..., "route": ...}`` as canonical JSON.
    """
    fields = type(route).codec.encode(route)
    return canonical_json({"fields": fields, "route": _name(type(route))})


def parse_route(key: str) -> Route | None:
    """Return the route a string names, or None when it names none.

    Args:
        key: A string the host handed back.

    Returns:
        The route, or None for anything that is not a known route's key.
    """
    try:
        raw = json.loads(key)
    except ValueError:
        return None
    if not isinstance(raw, dict) or set(raw) != {"fields", "route"}:
        return None
    cls = _ROUTES.get(raw["route"]) if isinstance(raw["route"], str) else None
    if cls is None:
        return None
    try:
        route: Route = cls.codec.decode(raw["fields"])
        return route
    except StateError:
        return None


@dataclass(frozen=True)
class Push:
    """Show ``route`` above the current screen.

    Attributes:
        route: The destination to show.
    """

    route: Route


@dataclass(frozen=True)
class Replace:
    """Show ``route`` in place of the current screen.

    Attributes:
        route: The destination to show.
    """

    route: Route


@dataclass(frozen=True)
class Pop:
    """Close the current screen and return to the one below it."""


NavOp = Push | Replace | Pop
"""One change to the back stack."""
