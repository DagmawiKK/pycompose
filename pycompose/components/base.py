"""Thin, immutable component construction driven by generated registry tables."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from difflib import get_close_matches
from types import CodeType
from typing import Any, ClassVar, NoReturn, cast

from pycompose.components.modifiers import Modifier
from pycompose.core import Node, Props
from pycompose.core.ids import call_location, call_site
from pycompose.core.props import JsonValue, props_from_kwargs, to_snake_case
from pycompose.errors import IrValidationError
from pycompose.ir.generated_validators import REGISTRY
from pycompose.ir.validator import validate_component
from pycompose.state.app_action import AppAction
from pycompose.utils.json_canonical import FrozenJsonValue, freeze_json

ActionTarget = str | AppAction[Any]
"""What an action prop takes: an app action, a binding of one, or a registry id."""


PropValue = JsonValue | AppAction[Any]
"""What a component prop takes before construction makes it wire data."""


_CONSTRUCTORS: set[CodeType] = set()
"""Every component ``__init__``, stepped over to find the app's declaring line."""


class Component(Node):
    """A Node with a registered component type and Pythonic prop names.

    Explicit ids are stable sibling keys; a component without one is keyed by
    the line that declares it. No automatic counters or object ids participate
    in composition. Emission produces plain IR Nodes when ids change.
    """

    __slots__ = ()
    component_type: ClassVar[str]

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
        values = {
            name: value.binding() if isinstance(value, AppAction) else value
            for name, value in props.items()
        }
        wire = cast(
            "dict[str, JsonValue | FrozenJsonValue]", props_from_kwargs(**values)
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
