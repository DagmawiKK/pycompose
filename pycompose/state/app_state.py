"""Typed application state: the app's own data, as a declared shape.

An app that keeps its data in a plain mapping has to hand-write the codec twice —
once to publish it, once to read it back — and gets no help when a field is
renamed or mistyped. Declaring the shape as a frozen dataclass and inheriting
:class:`AppState` makes the codec a property of the declaration instead:

    class Notes(AppState):
        notes: list[Note] = ()
        dark: bool = False

    return State(app=Notes(notes=notes, dark=dark))

The boundary still carries plain JSON. This only decides how the app describes it,
and it owns three things the app should never have to know about: the canonical
JSON freeze (which turns arrays into tuples), the camelCase spelling used on the
wire, and what happens when a save cannot be understood.
"""

from __future__ import annotations

import typing
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    TypeVar,
)

from pycompose.core.props import JsonValue, to_snake_case
from pycompose.core.reads import record
from pycompose.errors import StateError
from pycompose.state.app_state_codec import (
    _accepts,
    _decode_value,
    _encode_value,
)
from pycompose.state.app_state_types import _describe, _Field

__all__ = ["AppState", "Codec", "StateError"]

_StateT = TypeVar("_StateT", bound="AppState")


class Codec:
    """Converts one AppState subclass to and from canonical JSON.

    Attributes:
        cls: The class this codec belongs to.
        fields: One descriptor per declared field.
    """

    cls: type
    fields: tuple[_Field, ...]

    __slots__ = ("cls", "fields")

    def __init__(self, cls: type) -> None:
        """Describe every field of a class.

        Args:
            cls: The AppState subclass to describe.
        """
        self.cls = cls
        self.fields = _describe(cls)

    def encode(self, instance: Any) -> dict[str, JsonValue]:
        """Return this instance as plain JSON.

        Args:
            instance: An instance of the described class.

        Returns:
            A detached JSON mapping using camelCase keys.

        Raises:
            StateError: If a field holds a value its type forbids.
        """
        encoded: dict[str, JsonValue] = {}
        for field in self.fields:
            if field.loaded:
                continue
            value = getattr(instance, field.name, None)
            if value is None and field.optional:
                encoded[field.wire] = None
                continue
            if not _accepts(field.annotation, value):
                raise StateError(
                    f"{self.cls.__name__}.{field.name} cannot hold {value!r}"
                )
            encoded[field.wire] = _encode_value(field.annotation, value)
        return encoded

    def decode(self, raw: object) -> Any:
        """Return an instance built from JSON.

        Every field must be present or have a default, and every value must match
        its declared type. A save that does not satisfy this is rejected outright
        rather than half-applied: a notes app that silently drops one record is
        worse than one that starts fresh and says so.

        Args:
            raw: The published data, fresh from JSON or frozen on a State.

        Returns:
            An instance of the described class.

        Raises:
            StateError: If the data does not match the declared shape.
        """
        if not isinstance(raw, Mapping):
            raise StateError(f"{self.cls.__name__} data must be an object")
        by_wire = {field.wire: field for field in self.fields}
        by_name = {field.name: field for field in self.fields}

        values: dict[str, Any] = {}
        for key, value in raw.items():
            field = (
                by_wire.get(key)
                or by_name.get(key)
                or by_name.get(to_snake_case(str(key)))
            )
            if field is None:
                raise StateError(f"{self.cls.__name__} has no field {key!r}")
            if field.loaded:
                raise StateError(f"{self.cls.__name__}.{field.name} is never saved")
            if value is None and field.optional:
                values[field.name] = None
                continue
            if not _accepts(field.annotation, value):
                raise StateError(
                    f"{self.cls.__name__}.{field.name} cannot hold {value!r}"
                )
            values[field.name] = _decode_value(field.annotation, value)
        for field in self.fields:
            if field.name not in values and not field.default:
                raise StateError(f"{self.cls.__name__} is missing {field.name!r}")
        return self.cls(**values)


class _CodecSlot:
    """A per-class codec, built on first use.

    Building it eagerly is not possible: ``from __future__ import annotations``
    turns every annotation into a string, so a field referring to a class
    declared further down the module cannot be resolved at class-creation time.
    Deferring to first use is the only design that works with forward
    references, and forward references are the norm rather than the exception.

    It is a descriptor rather than a plain attribute so that a subclass never
    inherits its parent's codec by ordinary attribute lookup.
    """

    __slots__ = ()

    def __get__(self, instance: object, owner: type) -> Codec:
        """Return this class's codec, building it once.

        Args:
            instance: The instance, always None for class access.
            owner: The class being accessed.

        Returns:
            The codec describing that class.

        Raises:
            AttributeError: If the class is not a finished dataclass yet.
        """
        if not hasattr(owner, "__dataclass_fields__"):
            # dataclass probes class attributes while it is still building the
            # class. Answering here would recurse straight back into it.
            raise AttributeError("codec")
        holder: Any = owner
        cached: Codec | None = holder.__dict__.get("_codec_cache")
        if cached is None:
            cached = Codec(owner)
            holder._codec_cache = cached
        return cached


class _AppStateMeta(type):
    """Applies dataclass semantics and gives every subclass its own codec slot."""

    def __new__(
        cls,
        name: str,
        bases: tuple[type, ...],
        namespace: dict[str, Any],
    ) -> type:
        """Build the class as a frozen dataclass with its own codec slot.

        The slot is installed after ``dataclass`` has run, because a class
        attribute present beforehand is read as a field default — and building a
        codec from a half-built class fails. Assigning it afterwards still lands
        in this class's own ``__dict__``, so a subclass shadows rather than
        inherits its parent's codec.

        Subclasses are frozen dataclasses automatically and must not be decorated
        again: ``frozen=True`` writes ``__setattr__``, and applying it twice is an
        error rather than a no-op.

        Args:
            name: The class name.
            bases: The base classes.
            namespace: The class body.

        Returns:
            The new class.
        """
        installed: Any = dataclass(frozen=True)(
            type.__new__(cls, name, bases, namespace)
        )
        installed.codec = _CodecSlot()
        installed._codec_cache = None
        return typing.cast("type", installed)


class AppState(metaclass=_AppStateMeta):
    """Base for the app's own state, declared rather than hand-encoded.

    Subclass it and annotate the fields; the codec is derived from those
    annotations. Subclasses are frozen dataclasses already, so there is no
    ``@dataclass`` to remember and no chance of forgetting it on one screen.
    """

    if TYPE_CHECKING:
        # Declared for type checkers only. At runtime the metaclass installs the
        # descriptor, and an annotated attribute here would be read by dataclass
        # as a field — turning the codec into a constructor argument.
        codec: ClassVar[Codec]

        # A type checker cannot see through the metaclass, so it does not know a
        # subclass is a dataclass and would reject every keyword argument. The
        # real check on a declared state happens in the codec, at runtime, on
        # every field of every transition.
        def __init__(self, **changes: Any) -> None: ...

    def __getattribute__(self, name: str) -> Any:
        """Read one attribute, noting a field read for fine-grained reuse.

        Args:
            name: The attribute.

        Returns:
            Its value.
        """
        if name in object.__getattribute__(type(self), "__dataclass_fields__"):
            record(self, name)
        return object.__getattribute__(self, name)

    def evolve(self: _StateT, **changes: Any) -> _StateT:
        """Return a copy of this state with fields replaced.

        Args:
            **changes: Fields to replace.

        Returns:
            A new instance of the same class.
        """
        return typing.cast("_StateT", replace(typing.cast("Any", self), **changes))
