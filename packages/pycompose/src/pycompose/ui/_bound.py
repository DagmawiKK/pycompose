"""A binding as it crosses the wire, and whether it may fill a prop at all.

A binding is a target the host travels to with no Python per frame, so it can
only stand where the host has something to animate with and where the value is
read in the phase the binding names. Both are facts about the prop, resolved by
the generator from the pin; neither is a preference a caller may override.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from pycompose.errors import IrValidationError
from pycompose.model.catalog.lock import REGISTRY
from pycompose.model.catalog.props import PropDef
from pycompose.model.nodes.props import JsonValue, to_camel_case
from pycompose.model.programs.bindings import (
    Binding,
    Phase,
    animatable,
    check_binding,
    lower_binding,
)
from pycompose.model.programs.expressions import lower_expression


def lower_prop(component: str, name: str, value: object) -> JsonValue:
    """A prop as the wire states it: an expression written out, a binding lowered.

    A generated constructor lowers every prop the host can animate. This catches
    the rest, so a binding on a prop the pin gives no converter is refused by
    the rules with that reason, rather than failing as wire data.

    Args:
        component: The component's catalog name.
        name: The prop's ``snake_case`` keyword.
        value: What the app passed, after its action was lowered.

    Returns:
        The value the node stores.
    """
    if not isinstance(value, Binding):
        # An expression is wire data from here on; emission resolves its keys.
        return lower_expression(value)
    declared = REGISTRY.components.get(component)
    prop = declared.props.get(to_camel_case(name)) if declared is not None else None
    phase = prop.phase if prop is not None else None
    return lower_binding(value, cast("Phase", phase or "composition"))


def binding_refusal(value: object, prop: PropDef) -> str | None:
    """Why a binding cannot fill this prop, or None when it can.

    Args:
        value: The ``{"type": "binding", ...}`` object.
        prop: The definition of the prop it fills.

    Returns:
        The reason to refuse it, or None.
    """
    if not animatable(prop):
        return f"no animation converter for a {prop.type} prop"
    try:
        _target, phase = check_binding(cast("Mapping[str, object]", value))
    except IrValidationError as exc:
        return str(exc)
    if prop.phase is not None and phase != prop.phase:
        return f"this prop is read in {prop.phase}"
    return None
