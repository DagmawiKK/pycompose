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

import types
import typing
from collections.abc import Mapping, Sequence
from dataclasses import MISSING, dataclass, fields, replace
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Literal,
    TypeVar,
    Union,
    get_args,
    get_origin,
    get_type_hints,
)

from pycompose.core.props import JsonValue, to_camel_case, to_snake_case
from pycompose.errors import StateError

__all__ = ["AppState", "Codec", "StateError"]

_PRIMITIVES: dict[Any, tuple[type, ...]] = {
    bool: (bool,),
    int: (int,),
    float: (int, float),
    str: (str,),
}

_SEQUENCE_ORIGINS: tuple[Any, ...] = (list, tuple, set, frozenset)

_StateT = TypeVar("_StateT", bound="AppState")


def _is_primitive(annotation: Any, value: object) -> bool:
    """Return whether a value satisfies a primitive annotation.

    ``bool`` is checked before ``int`` because ``bool`` is a subclass of ``int``,
    and an ``int`` field silently holding ``True`` is exactly the kind of bug a
    declared state exists to prevent.

    Args:
        annotation: The annotated type.
        value: The value to check.

    Returns:
        True when the value is acceptable for that type.
    """
    if annotation is bool:
        return isinstance(value, bool)
    if annotation is int:
        return isinstance(value, int) and not isinstance(value, bool)
    if annotation is float:
        return isinstance(value, int | float) and not isinstance(value, bool)
    return annotation is str and isinstance(value, str)


class _Field:
    """One declared field, with the conversions that field needs.

    Attributes:
        name: The Python attribute name.
        wire: The camelCase key this field travels under.
        annotation: The declared type.
        optional: Whether the field may be None.
        default: Whether the field may be absent entirely.
    """

    name: str
    wire: str
    annotation: Any
    optional: bool
    default: bool

    __slots__ = ("annotation", "default", "name", "optional", "wire")

    def __init__(
        self,
        name: str,
        annotation: Any,
        optional: bool,
        default: bool,
    ) -> None:
        """Describe one field.

        Args:
            name: The Python attribute name.
            annotation: The declared type.
            optional: Whether the field may be None.
            default: Whether the field may be absent entirely.
        """
        self.name = name
        self.wire = to_camel_case(name)
        self.annotation = annotation
        self.optional = optional
        self.default = default


def _describe(cls: type) -> tuple[_Field, ...]:
    """Return the declared fields of an AppState subclass.

    Args:
        cls: The subclass to inspect.

    Returns:
        One descriptor per field.

    Raises:
        StateError: If an annotation names a type this codec cannot carry.
    """
    try:
        hints = get_type_hints(cls)
    except Exception as exc:
        raise StateError(f"{cls.__name__} has unresolvable type hints") from exc

    described: list[_Field] = []
    for field in fields(cls):
        annotation = hints.get(field.name, field.type)
        annotation, optional = _unwrap_optional(annotation)
        _require_supported(cls, field.name, annotation)
        described.append(
            _Field(
                name=field.name,
                annotation=annotation,
                optional=optional or _is_optional(field.type),
                default=field.default is not MISSING
                or field.default_factory is not MISSING,
            )
        )
    return tuple(described)


def _unwrap_optional(annotation: Any) -> tuple[Any, bool]:
    """Return an annotation with any Optional wrapper removed.

    Args:
        annotation: The declared annotation.

    Returns:
        The underlying type, and whether the field was declared Optional.
    """
    origin = get_origin(annotation)
    if origin in (Union, types.UnionType):
        options = [
            option for option in get_args(annotation) if option is not type(None)
        ]
        if len(options) == 1 and type(None) in get_args(annotation):
            return options[0], True
    return annotation, False


def _is_optional(annotation: Any) -> bool:
    """Return whether an annotation admits None.

    Args:
        annotation: The declared annotation.

    Returns:
        True when None is a permitted value.
    """
    return type(None) in get_args(annotation)


def _require_supported(cls: type, name: str, annotation: Any) -> None:
    """Reject an annotation the canonical JSON codec cannot carry.

    Args:
        cls: The class being described, for the message.
        name: The field name, for the message.
        annotation: The annotation to check.

    Raises:
        StateError: If the annotation is not supported.
    """
    if annotation in _PRIMITIVES or annotation is Any:
        return
    origin = get_origin(annotation)
    if origin in (list, set, frozenset, tuple) or origin is Union:
        return
    if origin is dict:
        return
    if origin is Literal:
        return
    if isinstance(annotation, type) and issubclass(annotation, AppState):
        return
    if _is_dataclass(annotation):
        return
    raise StateError(f"{cls.__name__}.{name} has an unsupported type: {annotation!r}")


def _is_dataclass(annotation: Any) -> bool:
    """Return whether an annotation is a plain dataclass.

    Args:
        annotation: The annotation to check.

    Returns:
        True when the annotation is a dataclass.
    """
    return isinstance(annotation, type) and hasattr(annotation, "__dataclass_fields__")


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

    def evolve(self: _StateT, **changes: Any) -> _StateT:
        """Return a copy of this state with fields replaced.

        Args:
            **changes: Fields to replace.

        Returns:
            A new instance of the same class.
        """
        return typing.cast("_StateT", replace(typing.cast("Any", self), **changes))
