"""One prop as the Python constructor spells it: annotation, storage, note.

A constructor's parameter is three facts about the same prop: the type an app
may pass (a binding included, when the host can animate to it), what the body
stores (the wire form of that binding), and the one-line note a docstring gives
it.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from pycompose.model.programs.bindings import animatable
from pycompose_codegen.emit.overloads import python_name


def python_type(
    component: str,
    name: str,
    prop: dict[str, Any],
    aliases: Mapping[tuple[str, str], str],
) -> str:
    if prop["type"] == "enum":
        return aliases[(component, name)]
    if prop["type"] == "color":
        # A colour may follow a holder's stream, evaluated by the host.
        annotation = f"{'JsonValue' if 'valueType' in prop else 'str'} | Expression"
    elif prop["type"] in {"dp", "number"}:
        # A number may follow a holder's stream, evaluated by the host.
        annotation = "int | float | Expression"
    elif "valueType" in prop:
        annotation = "JsonValue"
    else:
        annotation = {
            "string": "str",
            "color": "str",
            "resource": "str",
            "actionId": "ActionTarget",
            "boolean": "bool",
            "integer": "int",
            "durationMs": "int",
            "number": "int | float",
            "dp": "int | float",
            "modifier": "Modifier",
            "draw": "HostFunction | BoundFunction",
        }[prop["type"]]
    if animatable(prop):
        # The host animates to the target the app states with animate().
        annotation += " | Binding"
    return annotation


def stored_value(field: str, prop: dict[str, Any]) -> str | None:
    """What a constructor stores for one prop, when it is not the argument itself.

    Args:
        field: The prop's wire name.
        prop: The prop's schema entry.

    Returns:
        The expression to store, or None to store the argument unchanged.
    """
    if prop["type"] == "draw":
        return f"{python_name(field)}.to_wire()"
    if not animatable(prop):
        return None
    phase = json.dumps(prop.get("phase", "composition"))
    return f"lower_binding({python_name(field)}, {phase})"


def python_argument(
    component: str,
    field: str,
    prop: dict[str, Any],
    aliases: Mapping[tuple[str, str], str],
) -> tuple[str, str]:
    annotation = python_type(component, field, prop, aliases)
    if prop.get("nullable"):
        annotation += " | None"
    if prop.get("required"):
        return annotation, f"Required native {field}."
    if prop.get("nullable"):
        return (
            annotation + " | _Unset = UNSET",
            f"Native {field}; omitted uses its default; None is null.",
        )
    return annotation + " | None = None", f"Native {field}; None uses its default."
