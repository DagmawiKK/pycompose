"""One deterministic JSON writer for the wire contract."""

from __future__ import annotations

import json
from collections.abc import Mapping
from types import MappingProxyType
from typing import TypeAlias

from pycompose.errors import IrValidationError

__all__ = ["FrozenJsonValue", "JsonValue", "canonical_json", "freeze_json", "thaw_json"]

JsonValue: TypeAlias = (  # noqa: UP040
    "str | int | float | bool | None | dict[str, JsonValue] | list[JsonValue]"
)
FrozenJsonValue: TypeAlias = (  # noqa: UP040
    "str | int | float | bool | None | Mapping[str, FrozenJsonValue]"
    " | tuple[FrozenJsonValue, ...]"
)


def freeze_json(value: object) -> FrozenJsonValue:
    """Detach JSON data and recursively make objects/arrays read-only.

    Args:
        value: JSON data or an already frozen JSON value.

    Returns:
        Scalars, read-only mappings and tuples.

    Raises:
        IrValidationError: If a value is outside the JSON vocabulary.
    """
    try:
        return _freeze(value)
    except RecursionError as exc:
        raise IrValidationError("cyclic or excessively nested JSON value") from exc


def _freeze(value: object) -> FrozenJsonValue:
    if isinstance(value, Mapping):
        result: dict[str, FrozenJsonValue] = {}
        for key, child in value.items():
            if not isinstance(key, str):
                raise IrValidationError("JSON object keys must be strings")
            result[key] = _freeze(child)
        return MappingProxyType(result)
    if isinstance(value, list | tuple):
        return tuple(_freeze(child) for child in value)
    if value is None or isinstance(value, str | int | float | bool):
        return value
    raise IrValidationError("value is not JSON-compatible")


def thaw_json(value: object) -> JsonValue:
    """Copy frozen JSON values into ordinary wire objects and arrays.

    Args:
        value: A frozen or ordinary JSON value.

    Returns:
        Detached dictionaries/lists and JSON scalars.

    Raises:
        IrValidationError: If a value is outside the JSON vocabulary.
    """
    if isinstance(value, Mapping):
        result: dict[str, JsonValue] = {}
        for key, child in value.items():
            if not isinstance(key, str):
                raise IrValidationError("JSON object keys must be strings")
            result[key] = thaw_json(child)
        return result
    if isinstance(value, list | tuple):
        return [thaw_json(child) for child in value]
    if value is None or isinstance(value, str | int | float | bool):
        return value
    raise IrValidationError("value is not JSON-compatible")


def canonical_json(value: object) -> str:
    """Encode JSON with sorted objects, finite numbers and no whitespace.

    Uses Python 3.12's deterministic shortest-round-trip float formatting;
    this is the project's canonical form, not an RFC 8785 implementation.

    Args:
        value: JSON-compatible data to encode.

    Returns:
        Canonical text, encodable as UTF-8.

    Raises:
        IrValidationError: If the data is not finite, valid UTF-8 JSON.
    """
    try:
        _check_keys(value)
        result = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        result.encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise IrValidationError("invalid JSON value", detail=str(exc)) from exc
    return result


def _check_keys(value: object) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise TypeError("JSON object keys must be strings")
            _check_keys(child)
    elif isinstance(value, list):
        for child in value:
            _check_keys(child)
    elif value is not None and not isinstance(value, str | int | float | bool):
        raise TypeError("value is not JSON-compatible")
