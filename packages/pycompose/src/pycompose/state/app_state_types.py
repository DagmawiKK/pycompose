"""Annotation introspection for the app state codec.

Which scalars cross the wire as JSON, how an annotation describes itself as a
frozen dataclass, and where an optional or sequence hides its inner type. One
frozen-descriptor record (:class:`_Field`) answers "what is this app state
field" once per class, and the two tables (:data:`_PRIMITIVES`,
:data:`_SEQUENCE_ORIGINS`) carry the wire-supported kinds.

Value conversions live in ``app_state_codec``; the public types
(:class:`AppState`, :class:`Codec`) live in ``app_state``.
"""

from __future__ import annotations

import types
from dataclasses import MISSING, fields
from typing import (
    Annotated,
    Any,
    Literal,
    TypeVar,
    Union,
    get_args,
    get_origin,
    get_type_hints,
)

from pycompose.errors import StateError
from pycompose.model.nodes.props import to_camel_case

T = TypeVar("T")


class _LoadedMarker:
    """Marks a field filled by the app at run time and never saved."""

    def __repr__(self) -> str:
        return "Loaded"


LOADED = _LoadedMarker()

Loaded = Annotated[T, LOADED]
"""A field the app refills from its data, so it is never saved for process death.

``notes: Loaded[tuple[Note, ...]] = ()`` keeps a screen's data out of the saved
state, which the platform caps at a few hundred kilobytes; the view model fills it
again from its repository. A loaded field needs a default for that reason.
"""

_PRIMITIVES: dict[Any, tuple[type, ...]] = {
    bool: (bool,),
    int: (int,),
    float: (int, float),
    str: (str,),
}

_SEQUENCE_ORIGINS: tuple[Any, ...] = (list, tuple, set, frozenset)


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
        loaded: Whether the app refills the field, so it is never saved.
    """

    name: str
    wire: str
    annotation: Any
    optional: bool
    default: bool
    loaded: bool

    __slots__ = ("annotation", "default", "loaded", "name", "optional", "wire")

    def __init__(
        self,
        name: str,
        annotation: Any,
        optional: bool,
        default: bool,
        loaded: bool = False,
    ) -> None:
        """Describe one field.

        Args:
            name: The Python attribute name.
            annotation: The declared type.
            optional: Whether the field may be None.
            default: Whether the field may be absent entirely.
            loaded: Whether the app refills the field, so it is never saved.
        """
        self.name = name
        self.wire = to_camel_case(name)
        self.annotation = annotation
        self.optional = optional
        self.default = default
        self.loaded = loaded


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
        hints = get_type_hints(cls, include_extras=True)
    except Exception as exc:
        raise StateError(f"{cls.__name__} has unresolvable type hints") from exc

    described: list[_Field] = []
    for field in fields(cls):
        annotation = hints.get(field.name, field.type)
        loaded = False
        if get_origin(annotation) is Annotated:
            loaded = any(extra is LOADED for extra in annotation.__metadata__)
            annotation = get_args(annotation)[0]
        annotation, optional = _unwrap_optional(annotation)
        _require_supported(cls, field.name, annotation)
        default = field.default is not MISSING or field.default_factory is not MISSING
        if loaded and not default:
            raise StateError(
                f"{cls.__name__}.{field.name} is loaded and needs a default"
            )
        described.append(
            _Field(
                name=field.name,
                annotation=annotation,
                optional=optional or _is_optional(field.type),
                default=default,
                loaded=loaded,
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
    from pycompose.state.app_state import AppState

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
