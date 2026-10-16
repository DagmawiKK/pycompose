"""Pure Python composables, evaluated by a separate expansion pass."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Generic, ParamSpec

from pycompose.core.context import context, has_context
from pycompose.core.expansion import DeferredNode, expand_nodes
from pycompose.core.node import Node
from pycompose.errors import IrError, IrValidationError

__all__ = [
    "Composable",
    "Content",
    "composable",
    "content_nodes",
    "expand",
    "slot_nodes",
]
P = ParamSpec("P")
Content = Node | Sequence[Node] | Callable[[], Node | Sequence[Node]]


@dataclass(frozen=True, slots=True, init=False, kw_only=True)
class _Slot(DeferredNode):
    function: Callable[[], Node | Sequence[Node]]

    def __init__(self, key: str, function: Callable[[], Node | Sequence[Node]]) -> None:
        super(_Slot, self).__init__(id=key, type="@slot")
        object.__setattr__(self, "function", function)

    @property
    def recursion_key(self) -> object:
        return (type(self.function), id(self.function))

    @property
    def source(self) -> str:
        return f"content slot {self.id}"

    def build(self) -> tuple[Node, ...]:
        value = self.function()
        if callable(value):
            raise IrValidationError("slot must return nodes, not a callable")
        return content_nodes(value, key=self.id)


def content_nodes(value: Content, *, key: str) -> tuple[Node, ...]:
    """Normalize content without running Python content functions.

    Args:
        value: One node, ordered nodes, or a zero-argument content function.
        key: Stable namespace for a deferred content function.

    Returns:
        Native or deferred child declarations in construction order.

    Raises:
        IrValidationError: If content does not contain nodes.
    """
    if isinstance(value, Node):
        return (value,)
    if callable(value):
        return (_Slot(key, value),)
    if not isinstance(value, Sequence) or any(
        not isinstance(item, Node) for item in value
    ):
        raise IrValidationError("content must be a Node, node sequence, or callable")
    return tuple(value)


def slot_nodes(value: Content, *, key: str, slot: str) -> tuple[Node, ...]:
    """Normalize one named slot's content and mark every node with the slot.

    A named slot is filled with explicit nodes: a content function carries its
    own deferred identity, and a slot is a structural fact the parent states.

    Args:
        value: One node or ordered nodes for the slot.
        key: Stable namespace reported in validation errors.
        slot: Declared ``camelCase`` slot name.

    Returns:
        Child declarations carrying the slot, in construction order.

    Raises:
        IrValidationError: If the value is not a node or node sequence, or a
            deferred content function was supplied for a slot.
    """
    if callable(value):
        raise IrValidationError(
            "a named slot takes nodes, not a content function", node_id=key, prop=slot
        )
    nodes = content_nodes(value, key=key)
    return tuple(node.with_slot(slot) for node in nodes)


def _detach(value: object, active: set[int] | None = None) -> object:
    if not isinstance(value, list | tuple | Mapping | set | frozenset):
        return value
    seen = set() if active is None else active
    if id(value) in seen:
        raise IrValidationError("cyclic composable input")
    seen.add(id(value))
    try:
        if isinstance(value, list | tuple):
            return tuple(_detach(item, seen) for item in value)
        if isinstance(value, Mapping):
            return MappingProxyType(
                {key: _detach(item, seen) for key, item in value.items()}
            )
        return frozenset(_detach(item, seen) for item in value)
    finally:
        seen.remove(id(value))


def _argument_key(value: object) -> object:
    if isinstance(value, str | int | float | bool) or value is None:
        return (type(value), value)
    if isinstance(value, tuple):
        return tuple(_argument_key(item) for item in value)
    if isinstance(value, Mapping):
        return tuple(
            (_argument_key(key), _argument_key(item)) for key, item in value.items()
        )
    if isinstance(value, frozenset):
        return frozenset(_argument_key(item) for item in value)
    return (type(value), id(value))


@dataclass(frozen=True, slots=True, init=False, kw_only=True)
class _Call(DeferredNode):
    definition: Composable[Any]
    arguments: Mapping[str, Any]
    key: object

    def __init__(
        self, definition: Composable[Any], id: str, arguments: Mapping[str, Any]
    ) -> None:
        super(_Call, self).__init__(id=id, type="@composable")
        object.__setattr__(self, "definition", definition)
        detached = _detach(arguments)
        object.__setattr__(self, "arguments", detached)
        object.__setattr__(self, "key", (definition, _argument_key(detached)))

    @property
    def recursion_key(self) -> object:
        return self.key

    @property
    def source(self) -> str:
        return self.definition.source

    def build(self) -> tuple[Node, ...]:
        node = self.definition.function(**self.arguments)
        if not isinstance(node, Node):
            raise IrValidationError("composable must return one Node")
        return (node,)


class Composable(Generic[P]):
    """Importable composition definition; each call creates a deferred instance.

    Functions must be synchronous and pure with respect to their inputs. Python
    cannot prove absence of I/O or mutations; this interface does not pretend to
    enforce that. Caller-owned built-in containers are detached at declaration.
    A modifier is an ordinary explicit prop: forward it to the returned root as
    in Compose. Expansion never applies it a second time.
    """

    def __init__(self, function: Callable[P, Node]) -> None:
        if not inspect.isfunction(function):
            raise IrValidationError("composable requires a Python function")
        self.function = function
        self.signature = inspect.signature(function)
        self.__name__ = function.__name__
        self.__doc__ = function.__doc__
        self.__annotations__ = function.__annotations__.copy()
        self.__wrapped__ = function
        code = function.__code__
        self.source = (
            f"{function.__qualname__} ({code.co_filename}:{code.co_firstlineno})"
        )
        unsupported = any(
            parameter.kind
            in {inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.VAR_POSITIONAL}
            for parameter in self.signature.parameters.values()
        )
        if (
            "id" in self.signature.parameters
            or unsupported
            or inspect.iscoroutinefunction(function)
        ):
            raise IrValidationError("composable reserves id and must be synchronous")
        parameters = [
            inspect.Parameter("id", inspect.Parameter.KEYWORD_ONLY, annotation=str),
            *(
                parameter.replace(kind=inspect.Parameter.KEYWORD_ONLY)
                if parameter.kind == inspect.Parameter.POSITIONAL_OR_KEYWORD
                else parameter
                for parameter in self.signature.parameters.values()
            ),
        ]
        self.__signature__ = inspect.Signature(parameters, return_annotation=Node)
        self.__annotations__.update({"id": str, "return": Node})

    def _from_context(self, props: dict[str, Any]) -> dict[str, Any]:
        """Fill omitted optional inputs from the app context.

        A parameter left at its ``None`` default, whose name the app context
        carries, is filled from that context. This is how a screen binds a
        control without every caller threading the registry down to it -- the
        same bargain Compose strikes with ``LocalConfiguration.current``.

        Only ``None`` is filled and never another value, so an explicit ``None``
        and an omitted argument stay distinguishable. A required parameter is
        filled too when the context carries it; when neither the caller nor the
        context supplies one, the signature check below reports it exactly as it
        would any other missing argument.

        Args:
            props: The props as supplied by the caller.

        Returns:
            The props to declare with.
        """
        if not has_context():
            return props
        ambient = context()
        filled = dict(props)
        for name in self.signature.parameters:
            if name == "id" or name not in ambient:
                continue
            # Only an omitted or explicitly-None argument is filled. Anything
            # the caller passed is theirs, whatever it is.
            if name in filled and filled[name] is not None:
                continue
            filled[name] = ambient.get(name)
        return filled

    def __call__(self, *, id: str, **props: Any) -> Node:
        """Declare an instance without executing its function.

        Args:
            id: Stable key distinguishing this instance from its siblings.
            **props: Explicit function inputs, including content and modifiers.

        Returns:
            A frozen declaration evaluated during expansion.

        Raises:
            IrValidationError: If props do not match the function signature.
        """
        props = self._from_context(props)
        try:
            self.signature.bind(**props)
        except TypeError as exc:
            raise IrValidationError(
                "invalid composable props",
                node_id=id,
                source=self.source,
                reason=str(exc),
            ) from exc
        try:
            return _Call(self, id, props)
        except (IrError, RecursionError, TypeError) as exc:
            raise IrValidationError(
                "invalid composable declaration",
                node_id=id,
                source=self.source,
                reason=str(exc),
            ) from exc


def composable(function: Callable[P, Node]) -> Composable[P]:
    """Define a reusable composition without adding a native registry entry.

    Args:
        function: Pure function returning one native node or composable instance.

    Returns:
        An importable definition accepting an instance id and the function props.
    """
    return Composable(function)


def expand(root: Node) -> Node:
    """Evaluate Python declarations before emission, validation and serialization.

    Args:
        root: Native or deferred app declaration.

    Returns:
        A primitive-only root, sharing unchanged native branches by identity.
    """
    return expand_nodes(root)
