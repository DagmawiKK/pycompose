"""Thin, immutable component construction driven by generated registry tables."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from difflib import get_close_matches
from types import CodeType
from typing import Any, ClassVar, NoReturn, TypeAlias, cast

from pycompose.errors import IrValidationError
from pycompose.model.canonical import FrozenJsonValue, freeze_json
from pycompose.model.catalog.lock import REGISTRY
from pycompose.model.nodes import Node, Props
from pycompose.model.nodes.expressions import Expression
from pycompose.model.nodes.ids import call_location, call_site
from pycompose.model.nodes.props import JsonValue, props_from_kwargs, to_snake_case
from pycompose.model.nodes.values import _Unset, named_value
from pycompose.ui._generated.values import Color
from pycompose.ui._rules import validate_component
from pycompose.ui.intents import Intent, lower_action
from pycompose.ui.modifier import Modifier

ActionTarget = str | Intent | type[Intent]
"""What an action prop takes: an intent, an intent class, or a registry action id."""


# A string alias: the JSON alias is itself a string, and cannot take ``|``.
PropValue: TypeAlias = "JsonValue | Intent | type[Intent] | Expression"  # noqa: UP040
"""What a component prop takes before construction makes it wire data."""


_CONSTRUCTORS: set[CodeType] = set()
"""Every component ``__init__``, stepped over to find the app's declaring line."""


_COMMON = frozenset({"id", "modifier", "children", "content"})
"""Keywords every component takes, so none of them tells overloads apart."""


def _overload(
    cls: type[Component], positional: bool, kwargs: Mapping[str, Any]
) -> type[Component]:
    """The one overload of ``cls`` whose keywords a call fits, else ``cls``.

    An argument left at its absent value is not passed; children, given
    positionally or by name, are the ``content`` keyword. When nothing fits,
    ``cls`` is returned so its own constructor reports what is missing.
    """
    given = {
        key
        for key, value in kwargs.items()
        if value is not None and not isinstance(value, _Unset)
    } - _COMMON
    if positional or kwargs.get("children") or kwargs.get("content") is not None:
        given.add("content")
    fits = [
        overload
        for overload in (cls, *cls.overloads)
        if overload.required_keywords <= given <= overload.accepted_keywords
    ]
    return fits[0] if len(fits) == 1 else cls


class Component(Node):
    """A Node with a registered component type and Pythonic prop names.

    Explicit ids are stable sibling keys; a component without one is keyed by
    the line that declares it. No automatic counters or object ids participate
    in composition. Emission produces plain IR Nodes when ids change.
    """

    __slots__ = ()
    component_type: ClassVar[str]
    required_keywords: ClassVar[frozenset[str]] = frozenset()
    accepted_keywords: ClassVar[frozenset[str]] = frozenset()
    overloads: ClassVar[tuple[type[Component], ...]] = ()
    """The other overloads this name reaches; keywords choose among them."""

    def __new__(cls, *_children: Any, **kwargs: Any) -> Any:
        """Choose the overload a call means, or build a windowed declaration.

        ``Card(on_click=open, ...)`` and ``Card(...)`` are two native overloads
        behind one name: the keywords a call passes select exactly one, which
        codegen proves per name. The chosen class's ``__init__`` then runs.
        ``LazyColumn(items=notes, key=..., item=...)`` lists data rather than
        nodes; the host then asks for the window it shows.

        Args:
            *_children: Positional children, read by ``__init__``.
            **kwargs: The component's keyword arguments.

        Returns:
            A :class:`Windowed` declaration, or a new instance of the overload.
        """
        chosen = (
            _overload(cls, bool(_children), kwargs)
            if "overloads" in cls.__dict__
            else cls
        )
        item = kwargs.pop("item", None)
        if item is None:
            return super().__new__(chosen)
        from pycompose.ui.windowed import Windowed

        site = call_site(0, _CONSTRUCTORS | {Component.__new__.__code__})
        return Windowed(
            chosen,
            site=site,
            id=kwargs.pop("id", None),
            items=kwargs.pop("items", ()),
            key=kwargs.pop("key", None),
            item=item,
            **kwargs,
        )

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Record a subclass's constructor so call sites skip past it.

        Args:
            **kwargs: Passed on to ``object.__init_subclass__``.
        """
        super().__init_subclass__(**kwargs)
        constructor = cls.__dict__.get("__init__")
        if constructor is not None:
            _CONSTRUCTORS.add(constructor.__code__)

    def __init__(
        self,
        *,
        id: str | None = None,
        children: Sequence[Node] = (),
        modifier: Modifier | Mapping[str, JsonValue | FrozenJsonValue] | None = None,
        **props: PropValue,
    ) -> None:
        """Construct immutable IR and validate this component, not its subtree.

        Args:
            id: Stable sibling key or already-qualified node id. None keys the
                node by the line that declares it; a component carrying an
                action declared in a loop must still have an id, since only an
                id survives a reorder.
            children: Child nodes in render order.
            modifier: Ordered Modifier or a modifier wire object.
            **props: Snake_case props declared by the component registry.

        Raises:
            IrValidationError: If a prop name is not snake_case.
        """
        for name in props:
            if name != to_snake_case(name):
                raise IrValidationError(
                    "prop name is not snake_case", node_id=id or "", prop=name
                )
        # A control may take an app action itself; it binds nothing of its own.
        # An expression is wire data from here on; emission resolves its keys.
        values = {name: lower_action(value) for name, value in props.items()}
        wire = cast(
            "dict[str, JsonValue | FrozenJsonValue]", props_from_kwargs(**values)
        )
        declared = REGISTRY.components.get(self.component_type)
        for key, value in wire.items():
            rule = declared.props.get(key) if declared is not None else None
            if not isinstance(value, str) or rule is None:
                continue
            if rule.type == "color":
                wire[key] = _hex_color(value, id or "", key)
            elif rule.type == "enum" and rule.value_type is not None:
                wire[key] = cast(
                    "JsonValue",
                    named_value(rule.value_type, value, REGISTRY.value_types),
                )
        if modifier is not None:
            wire["modifier"] = freeze_json(
                modifier.values if isinstance(modifier, Modifier) else modifier
            )
        super().__init__(
            id=id or "",
            type=self.component_type,
            props=Props(wire),
            children=children,
            site="" if id else call_site(0, _CONSTRUCTORS),
        )
        try:
            validate_component(self)
        except IrValidationError as exc:
            _refuse(exc, self)
        keys: set[str] = set()
        for child in self.children:
            if not child.id:
                # The emitter derives these ids; they are not sibling keys.
                continue
            if child.id in keys:
                raise IrValidationError("duplicate child key", node_id=id, key=child.id)
            keys.add(child.id)


_CONSTRUCTORS.add(Component.__init__.__code__)


_HEX = "a colour is #RRGGBB, #AARRGGBB or a Color value"


def _hex_color(text: str, node_id: str, prop: str) -> JsonValue:
    """A colour written as ``#RRGGBB`` or ``#AARRGGBB``, as its tagged value.

    The wire carries one colour form, the family's tagged object, so the hex
    an app writes becomes it here.

    Args:
        text: The colour as written.
        node_id: The node it belongs to, for the error.
        prop: The prop it belongs to, for the error.

    Returns:
        The tagged ``Color``.

    Raises:
        IrValidationError: If the text is not such a hex colour.
    """
    digits = text[1:]
    if not text.startswith("#") or len(digits) not in (6, 8):
        raise IrValidationError(
            "a colour is #RRGGBB, #AARRGGBB or a Color value",
            node_id=node_id,
            prop=prop,
        )
    try:
        bits = int(digits, 16)
    except ValueError:
        raise IrValidationError(
            "a colour is #RRGGBB, #AARRGGBB or a Color value",
            node_id=node_id,
            prop=prop,
        ) from None
    return Color(bits | 0xFF000000 if len(digits) == 6 else bits)


def _refuse(error: IrValidationError, node: Component) -> NoReturn:
    """Add where a refused declaration is, and what its prop could have been.

    Args:
        error: The validator's refusal of this one node.
        node: The node it refused.

    Raises:
        IrValidationError: The same refusal, naming the app's file and line,
            and for a prop with a closed set of values, the values and the
            closest one.
    """
    context = dict(error.context)
    context["source"] = call_location(1, _CONSTRUCTORS)
    prop = context.get("prop")
    definition = REGISTRY.components.get(node.type)
    rule = definition.props.get(str(prop)) if definition is not None else None
    if rule is not None and rule.values:
        allowed = [str(value) for value in rule.values]
        context["expected"] = ", ".join(allowed)
        value = node.props.get(str(prop))
        close = get_close_matches(str(value), allowed, n=1) if value is not None else []
        if close:
            context["did_you_mean"] = close[0]
    raise IrValidationError(error.args[0] if error.args else "", **context) from None
