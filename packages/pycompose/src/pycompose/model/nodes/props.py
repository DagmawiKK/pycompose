"""Prop helpers: wire-name casing and the JSON value vocabulary.

Wire props are ``camelCase`` (the IR contract); the component layer accepts
``snake_case`` keyword arguments and converts them here. Pure stdlib.
"""

from __future__ import annotations

from typing import Final

from pycompose.model.canonical import JsonValue

__all__ = [
    "JsonValue",
    "is_camel_case",
    "props_from_kwargs",
    "to_camel_case",
    "to_snake_case",
]

_UNDERSCORE: Final[str] = "_"


def to_camel_case(name: str) -> str:
    """Convert a ``snake_case`` name to ``camelCase``.

    Args:
        name: The ``snake_case`` (or already ``camelCase``) name.

    Returns:
        The ``camelCase`` equivalent; empty input returns an empty string.
    """
    head, *tail = name.split(_UNDERSCORE)
    return head + "".join(part[:1].upper() + part[1:] for part in tail)


def to_snake_case(name: str) -> str:
    """Convert a ``camelCase`` or ``PascalCase`` name to ``snake_case``.

    Args:
        name: The mixed-case name.

    Returns:
        The ``snake_case`` equivalent.
    """
    snake: list[str] = []
    for index, char in enumerate(name):
        if char.isupper():
            if index:
                snake.append(_UNDERSCORE)
            snake.append(char.lower())
        else:
            snake.append(char)
    return "".join(snake)


def is_camel_case(name: str) -> bool:
    """Report whether ``name`` is a valid ``camelCase`` wire prop name.

    Args:
        name: The prop name to test.

    Returns:
        ``True`` when the name is non-empty, starts lowercase, and has no
        underscores.
    """
    return bool(name) and name[0].islower() and name == to_camel_case(name)


def props_from_kwargs(**kwargs: JsonValue) -> dict[str, JsonValue]:
    """Build a ``camelCase`` prop mapping from ``snake_case`` keyword args.

    Args:
        **kwargs: ``snake_case`` prop keyword arguments.

    Returns:
        A new mapping with ``camelCase`` keys.
    """
    return {to_camel_case(name): value for name, value in kwargs.items()}
