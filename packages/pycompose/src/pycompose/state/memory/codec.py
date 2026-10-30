"""Value conversions for the app state codec.

One function per shape the wire can carry: scalars, sequences, nullable
fields, nested frozen dataclasses and nested app states. The per-shape
dispatch tables (:data:`_CHECKS`, :data:`_ENCODERS`, :data:`_DECODERS`) map
annotations to the handler each shape runs, so adding one shape touches one
entry. :func:`_accepts` and :func:`_as_state` name the public state type, so
they resolve ``pycompose.state.memory.app_state`` lazily inside the call -- the codec
layer sits below it.

Imports and public types live in ``app_state_type`` leaves and ``app_state``.
"""

from __future__ import annotations

import types
import typing
from collections.abc import Mapping, Sequence
from dataclasses import MISSING, fields
from typing import (
    Any,
    Literal,
    Union,
    get_args,
    get_origin,
    get_type_hints,
)

from pycompose.errors import StateError
from pycompose.model.nodes.props import JsonValue, to_camel_case
from pycompose.state.memory.types import (
    _PRIMITIVES,
    _is_dataclass,
    _is_optional,
    _is_primitive,
    _unwrap_optional,
)

_CHECKS: dict[Any, Any] = {
    list: lambda annotation, value: isinstance(value, Sequence)
    and not isinstance(value, str | bytes)
    and all(_accepts(_item_type(annotation), entry) for entry in value),
    tuple: lambda annotation, value: isinstance(value, Sequence)
    and not isinstance(value, str | bytes)
    and all(_accepts(_item_type(annotation), entry) for entry in value),
    set: lambda annotation, value: isinstance(value, Sequence)
    and not isinstance(value, str | bytes)
    and all(_accepts(_item_type(annotation), entry) for entry in value),
    frozenset: lambda annotation, value: isinstance(value, Sequence)
    and not isinstance(value, str | bytes)
    and all(_accepts(_item_type(annotation), entry) for entry in value),
    Literal: lambda annotation, value: value in get_args(annotation),
    Union: lambda annotation, value: any(
        _accepts(option, value) for option in get_args(annotation)
    ),
    types.UnionType: lambda annotation, value: any(
        _accepts(option, value) for option in get_args(annotation)
    ),
    dict: lambda annotation, value: isinstance(value, Mapping)
    and all(_accepts(_value_type(annotation), entry) for entry in value.values()),
}


def _accepts(annotation: Any, value: object) -> bool:
    """Return whether a value is permissible for an annotation.

    Containers are checked element by element rather than by shape alone:
    ``list[Row]`` that only checks "is this a list" would accept a list of
    anything, which is precisely the bug a declared state exists to prevent.

    Args:
        annotation: The declared type.
        value: The value to check.

    Returns:
        True when the value can be stored in that field.
    """
    from pycompose.state.memory.app_state import AppState

    if annotation in _PRIMITIVES:
        return _is_primitive(annotation, value)
    if annotation is Any:
        return True

    check = _CHECKS.get(get_origin(annotation))
    if check is not None:
        return bool(check(annotation, value))

    if isinstance(annotation, type) and (
        issubclass(annotation, AppState) or _is_dataclass(annotation)
    ):
        # On the way in this is an encoded object, not yet an instance, so a
        # mapping is as acceptable as the class itself.
        return isinstance(value, annotation | Mapping)
    return False


def _as_state(annotation: object) -> type | None:
    """Return the AppState subclass an annotation names.

    Args:
        annotation: The annotation to inspect.

    Returns:
        The AppState subclass, or None when the annotation is not one.
    """
    from pycompose.state.memory.app_state import AppState

    if isinstance(annotation, type) and issubclass(annotation, AppState):
        return annotation
    return None


_ENCODERS: dict[Any, Any] = {
    list: lambda annotation, value: [
        _encode_value(_item_type(annotation), item) for item in value
    ],
    tuple: lambda annotation, value: [
        _encode_value(_item_type(annotation), item) for item in value
    ],
    set: lambda annotation, value: [
        _encode_value(_item_type(annotation), item) for item in value
    ],
    frozenset: lambda annotation, value: [
        _encode_value(_item_type(annotation), item) for item in value
    ],
    dict: lambda annotation, value: {
        str(key): _encode_value(_value_type(annotation), item)
        for key, item in value.items()
    },
    Literal: lambda _annotation, value: value,
}

_DECODERS: dict[Any, Any] = {
    list: lambda annotation, value: [
        _decode_value(_item_type(annotation), item) for item in value
    ],
    tuple: lambda annotation, value: tuple(
        _decode_value(_item_type(annotation), item) for item in value
    ),
    set: lambda annotation, value: {
        _decode_value(_item_type(annotation), item) for item in value
    },
    frozenset: lambda annotation, value: frozenset(
        _decode_value(_item_type(annotation), item) for item in value
    ),
    dict: lambda annotation, value: {
        str(key): _decode_value(_value_type(annotation), item)
        for key, item in value.items()
    },
    Literal: lambda _annotation, value: value,
}


def _encode_value(annotation: Any, value: object) -> JsonValue:
    """Return one field's value as canonical JSON.

    Frozen tuples and frozen mappings arrive here from a previous snapshot, and
    they become lists and objects again on the way out. The app never has to know
    that happened.

    Args:
        annotation: The declared type.
        value: The value to convert.

    Returns:
        A JSON-compatible value.
    """
    if annotation in _PRIMITIVES or annotation is Any:
        return typing.cast("JsonValue", value)
    origin = get_origin(annotation)
    if origin in _ENCODERS:
        return typing.cast("JsonValue", _ENCODERS[origin](annotation, value))
    if origin is Union:
        return typing.cast("JsonValue", _narrow(annotation, value, _encode_value))
    nested = _as_state(annotation)
    if nested is not None:
        return typing.cast("JsonValue", typing.cast("Any", nested).codec.encode(value))
    if _is_dataclass(annotation):
        return _dataclass_to(annotation, value)
    return typing.cast("JsonValue", value)


def _decode_value(annotation: Any, value: object) -> Any:
    """Return one field's value rebuilt from canonical JSON.

    Args:
        annotation: The declared type.
        value: The value to convert.

    Returns:
        A value ready to be stored in the field.
    """
    if annotation in _PRIMITIVES or annotation is Any:
        return value
    origin = get_origin(annotation)
    if origin in _DECODERS:
        return _DECODERS[origin](annotation, value)
    if origin is Union:
        return _narrow(annotation, value, _decode_value)
    nested = _as_state(annotation)
    if nested is not None:
        return typing.cast("Any", nested).codec.decode(value)
    if _is_dataclass(annotation):
        return _dataclass_from(annotation, value)
    return value


def _narrow(annotation: Any, value: object, convert: Any) -> Any:
    """Convert a value against the first union member that accepts it.

    Args:
        annotation: The union annotation.
        value: The value to convert.
        convert: Either _encode_value or _decode_value.

    Returns:
        The converted value, or the value itself when nothing accepts it.
    """
    for option in get_args(annotation):
        if _accepts(option, value):
            return convert(option, value)
    return value


def _dataclass_to(annotation: Any, value: object) -> dict[str, JsonValue]:
    """Return a plain dataclass as canonical JSON.

    Args:
        annotation: The dataclass type.
        value: The instance to convert.

    Returns:
        A JSON object with camelCase keys.
    """
    hints = get_type_hints(annotation)
    encoded: dict[str, JsonValue] = {}
    for entry in fields(annotation):
        member, _ = _unwrap_optional(hints.get(entry.name, entry.type))
        encoded[to_camel_case(entry.name)] = _encode_value(
            member, getattr(value, entry.name)
        )
    return encoded


def _dataclass_from(annotation: Any, raw: object) -> Any:
    """Build a plain dataclass from a JSON object.

    Args:
        annotation: The dataclass to build.
        raw: The JSON object.

    Returns:
        An instance of the dataclass.

    Raises:
        StateError: If the object does not match the dataclass.
    """
    if not isinstance(raw, Mapping):
        raise StateError(f"{annotation.__name__} data must be an object")
    hints = get_type_hints(annotation)
    values: dict[str, Any] = {}
    for entry in fields(annotation):
        key = to_camel_case(entry.name)
        if key in raw:
            declared, _ = _unwrap_optional(hints.get(entry.name, entry.type))
            member = raw[key]
            if member is None and _is_optional(hints.get(entry.name, entry.type)):
                values[entry.name] = None
                continue
            if not _accepts(declared, member):
                raise StateError(
                    f"{annotation.__name__}.{entry.name} cannot hold {member!r}"
                )
            values[entry.name] = _decode_value(declared, member)
        elif entry.default is MISSING and entry.default_factory is MISSING:
            raise StateError(f"{annotation.__name__} is missing {entry.name!r}")
        elif entry.default_factory is not MISSING:
            values[entry.name] = entry.default_factory()
        else:
            values[entry.name] = entry.default
    return annotation(**values)


def _item_type(annotation: Any) -> Any:
    """Return the element type of a container annotation.

    Args:
        annotation: The container annotation.

    Returns:
        The element type, or Any for a bare container.
    """
    args = get_args(annotation)
    if not args:
        return Any
    if len(args) == 2 and args[1] is Ellipsis:
        return args[0]
    return args[0]


def _value_type(annotation: Any) -> Any:
    """Return the value type of a mapping annotation.

    Args:
        annotation: The mapping annotation.

    Returns:
        The value type, or Any for a bare mapping.
    """
    args = get_args(annotation)
    return args[1] if len(args) == 2 else Any
