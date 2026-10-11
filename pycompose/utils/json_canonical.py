"""Detached JSON ownership, direct validation and canonical UTF-8 encoding.

For V value/key occurrences, each operation traverses O(V) data. Encoding also
costs O(B) scalar/output bytes and O(sum(k log k)) object-key ordering; validation
does not sort or build text. Iterator/active-path stacks scale with depth, and
encoding retains sorted keys only for active objects. Copying owns O(V) output;
byte encoding owns O(B) output. Internal frozen containers carry provenance so
unchanged values are safely reused; caller-provided proxies/tuples are detached.
Scalar-only containers use bounded-depth copying/encoding, never user-depth
recursion. Cycles are rejected on the active path, not by global deduplication.
"""

from __future__ import annotations

import json
import math
from collections.abc import ItemsView, Iterator, Mapping, ValuesView
from dataclasses import dataclass
from types import MappingProxyType
from typing import TypeAlias, cast

from pycompose.errors import IrValidationError

__all__ = [
    "FrozenJsonValue",
    "JsonValue",
    "canonical_json",
    "canonical_json_bytes",
    "check_json",
    "freeze_json",
    "thaw_json",
]

JsonValue: TypeAlias = (  # noqa: UP040
    "str | int | float | bool | None | dict[str, JsonValue] | list[JsonValue]"
)
FrozenJsonValue: TypeAlias = (  # noqa: UP040
    "str | int | float | bool | None | Mapping[str, FrozenJsonValue]"
    " | tuple[FrozenJsonValue, ...]"
)

_ENCODER = json.JSONEncoder(
    sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
)


@dataclass(frozen=True, slots=True, eq=False)
class _FrozenObject(Mapping[str, FrozenJsonValue]):
    _data: Mapping[str, FrozenJsonValue]
    flat: bool = False

    def __getitem__(self, key: str) -> FrozenJsonValue:
        return self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def items(self) -> ItemsView[str, FrozenJsonValue]:
        return self._data.items()

    def values(self) -> ValuesView[FrozenJsonValue]:
        return self._data.values()


class _FrozenArray(tuple[FrozenJsonValue, ...]):
    __slots__ = ()


@dataclass(slots=True)
class _CopyFrame:
    identity: int
    entries: Iterator[tuple[str | int, object]]
    output: dict[str, object] | list[object]
    key: str | int = 0


_DESCEND = object()


def _freeze_container(
    value: dict[str, object] | list[object], *, flat: bool = False
) -> object:
    if isinstance(value, dict):
        return _FrozenObject(
            MappingProxyType(cast(dict[str, FrozenJsonValue], value)), flat=flat
        )
    return _FrozenArray(cast(list[FrozenJsonValue], value))


def _copy_atomic(value: object, *, frozen: bool) -> object:
    if (frozen and isinstance(value, _FrozenObject | _FrozenArray)) or (
        value is None or isinstance(value, str | int | float)
    ):
        return value
    if isinstance(value, Mapping):
        if not all(
            child is None or isinstance(child, str | int | float)
            for child in value.values()
        ):
            return _DESCEND
        if any(not isinstance(key, str) for key in value):
            raise IrValidationError("JSON object keys must be strings")
        copied = dict(value)
        return _freeze_container(copied, flat=True) if frozen else copied
    if isinstance(value, list | tuple):
        if not all(
            child is None or isinstance(child, str | int | float) for child in value
        ):
            return _DESCEND
        return _FrozenArray(value) if frozen else list(value)
    raise IrValidationError("value is not JSON-compatible")


def _copy_json(value: object, *, frozen: bool) -> object:
    stack: list[_CopyFrame] = []
    active: set[int] = set()
    result: object
    while True:
        result = _copy_atomic(value, frozen=frozen)
        if result is _DESCEND:
            identity = id(value)
            if identity in active:
                raise IrValidationError("cyclic JSON value")
            active.add(identity)
            container = cast(
                Mapping[str, object] | list[object] | tuple[object, ...], value
            )
            frame = _CopyFrame(
                identity,
                iter(container.items())
                if isinstance(container, Mapping)
                else iter(enumerate(container)),
                {} if isinstance(container, Mapping) else [],
            )
            stack.append(frame)
        while stack:
            frame = stack[-1]
            if result is not _DESCEND:
                if isinstance(frame.output, dict):
                    frame.output[cast(str, frame.key)] = result
                else:
                    frame.output.append(result)
            try:
                frame.key, value = next(frame.entries)
                if isinstance(frame.output, dict) and not isinstance(frame.key, str):
                    raise IrValidationError("JSON object keys must be strings")
                break
            except StopIteration:
                stack.pop()
                active.remove(frame.identity)
                result = frame.output
                if frozen:
                    result = _freeze_container(frame.output)
        else:
            return result


def freeze_json(value: object) -> FrozenJsonValue:
    """Detach JSON data and recursively make objects/arrays read-only.

    Cycles or non-JSON vocabulary propagate IrValidationError. Values produced
    by this module are already detached and are reused rather than frozen again.

    Args:
        value: JSON data or an already frozen JSON value.

    Returns:
        Scalars, read-only mappings and tuples.

    """
    return cast(FrozenJsonValue, _copy_json(value, frozen=True))


def thaw_json(value: object) -> JsonValue:
    """Copy frozen JSON values into ordinary wire objects and arrays.

    Cycles or non-JSON vocabulary propagate IrValidationError.

    Args:
        value: A frozen or ordinary JSON value.

    Returns:
        Detached dictionaries/lists and JSON scalars.

    """
    return cast(JsonValue, _copy_json(value, frozen=False))


def canonical_json(value: object) -> str:
    """Encode JSON with sorted objects, finite numbers and no whitespace.

    Uses Python 3.12's deterministic shortest-round-trip float formatting;
    this is the project's canonical form, not an RFC 8785 implementation.
    Invalid values propagate IrValidationError from the byte encoder.

    Args:
        value: JSON-compatible data to encode.

    Returns:
        Canonical text, encodable as UTF-8.

    """
    return canonical_json_bytes(value).decode("utf-8")


def _scalar_bytes(value: object) -> bytes:
    if isinstance(value, str):
        return json.encoder.encode_basestring(value).encode("utf-8")
    if value is None:
        return b"null"
    if value is True:
        return b"true"
    if value is False:
        return b"false"
    if isinstance(value, int):
        return int.__repr__(value).encode("ascii")
    if isinstance(value, float):
        return _ENCODER.encode(value).encode("ascii")
    raise IrValidationError("value is not JSON-compatible")


@dataclass(slots=True)
class _WriteFrame:
    identity: int
    entries: Iterator[tuple[str | None, object]]
    closing: bytes
    started: bool = False


def _sorted_entries(value: Mapping[str, object]) -> Iterator[tuple[str | None, object]]:
    for key in sorted(value):
        yield key, value[key]


def _write_frame(value: object) -> tuple[_WriteFrame, bytes]:
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise IrValidationError("JSON object keys must be strings")
        return _WriteFrame(id(value), _sorted_entries(value), b"}"), b"{"
    if isinstance(value, list | _FrozenArray):
        entries = iter((None, child) for child in value)
        return _WriteFrame(id(value), entries, b"]"), b"["
    raise IrValidationError("value is not JSON-compatible")


def _tokens(value: object) -> Iterator[bytes]:
    stack: list[_WriteFrame] = []
    active: set[int] = set()
    while True:
        if value is None or isinstance(value, str | int | float):
            yield _scalar_bytes(value)
        elif isinstance(value, _FrozenObject) and value.flat:
            # Scalar-only objects have bounded encoder depth, even inside a deep IR.
            yield _ENCODER.encode(dict(value._data)).encode("utf-8")
        elif isinstance(value, _FrozenArray) and all(
            child is None or isinstance(child, str | int | float) for child in value
        ):
            yield _ENCODER.encode(value).encode("utf-8")
        else:
            frame, opening = _write_frame(value)
            if frame.identity in active:
                raise IrValidationError("cyclic JSON value")
            active.add(frame.identity)
            yield opening
            stack.append(frame)
        while stack:
            frame = stack[-1]
            try:
                key, value = next(frame.entries)
            except StopIteration:
                stack.pop()
                active.remove(frame.identity)
                yield frame.closing
                continue
            if frame.started:
                yield b","
            frame.started = True
            if key is not None:
                yield _scalar_bytes(key)
                yield b":"
            break
        else:
            return


def canonical_json_bytes(value: object) -> bytes:
    """Encode canonical UTF-8 without recursive traversal or intermediate text.

    Args:
        value: JSON data to encode.

    Returns:
        Deterministic UTF-8 bytes.

    Raises:
        IrValidationError: If data contains cycles or invalid JSON scalars/keys.
    """
    output = bytearray()
    try:
        if value is None or isinstance(value, str | int | float):
            return _scalar_bytes(value)
        for token in _tokens(value):
            output.extend(token)
    except (TypeError, ValueError, UnicodeError) as exc:
        raise IrValidationError("invalid JSON value", detail=str(exc)) from exc
    return bytes(output)


def _check_scalar(value: object) -> bool:
    if isinstance(value, str):
        str.encode(value, "utf-8")
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise IrValidationError("non-finite JSON number")
    elif isinstance(value, int):
        int.__repr__(value)
    elif value is not None:
        return False
    return True


def _value_children(value: object) -> Iterator[object]:
    if isinstance(value, Mapping):
        for key in value:
            if not isinstance(key, str):
                raise IrValidationError("JSON object keys must be strings")
            str.encode(key, "utf-8")
        return iter(value.values())
    if isinstance(value, list | _FrozenArray):
        return iter(value)
    raise IrValidationError("value is not JSON-compatible")


def check_json(value: object) -> None:
    """Validate ordinary/frozen JSON directly, without sorting or serialization.

    Args:
        value: Data to check for finite numbers, UTF-8 strings and JSON vocabulary.

    Raises:
        IrValidationError: If data cannot be encoded as canonical JSON.
    """
    stack: list[tuple[int, Iterator[object]]] = []
    active: set[int] = set()
    try:
        while True:
            if not _check_scalar(value):
                identity = id(value)
                if identity in active:
                    raise IrValidationError("cyclic JSON value")
                active.add(identity)
                children = _value_children(value)
                stack.append((identity, children))
            while stack:
                identity, children = stack[-1]
                try:
                    value = next(children)
                    break
                except StopIteration:
                    stack.pop()
                    active.remove(identity)
            else:
                return
    except (TypeError, ValueError, UnicodeError) as exc:
        raise IrValidationError("invalid JSON value", detail=str(exc)) from exc
