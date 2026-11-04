"""Text fields that keep what was typed until Python has answered it."""

from __future__ import annotations

from typing import Any

from pycompose_codegen.emit.adapters.fragments import Fragments

__all__ = ["EDIT_IMPORTS", "echoed_text", "echoes"]

EDIT_IMPORTS = frozenset(
    {"com.pycompose.renderer.edit", "com.pycompose.renderer.edited"}
)
"""The renderer's reconciler, which a reconciled field calls."""


def echoes(props: dict[str, Any]) -> bool:
    """Whether a component is a text field whose value comes back as its text.

    Args:
        props: The component's declared props, by wire name.

    Returns:
        True for a required string ``value`` and its ``onValueChange`` report.
    """
    value, change = props.get("value") or {}, props.get("onValueChange") or {}
    reported = [(f["name"], f["type"]) for f in change.get("payload") or []]
    return (
        value.get("type") == "string"
        and bool(value.get("required"))
        and change.get("type") == "actionId"
        and bool(change.get("required"))
        and reported == [("value", "string")]
    )


def echoed_text(props: dict[str, Any], out: Fragments) -> set[str]:
    """Render a text field's value through the host's edit reconciler.

    A field that showed each snapshot's text would apply the next keystroke to
    text one or more keys old, so keys typed faster than Python answers them
    would be lost. Each keystroke is reported numbered, and the field shows it
    until the app has answered every one; what the app states then is its own
    (``Edited``, shared with the host's hand-written fields).

    Args:
        props: The component's declared props, by wire name.
        out: Collects the rendered pieces.

    Returns:
        The props rendered here, or none for a component of another shape.
    """
    if not echoes(props):
        return set()
    out.locals.append(
        "val field = context.edited(model.id, model.props.value, "
        "model.props.onValueChange)"
    )
    out.arguments.append("value = field.value")
    out.arguments.append(
        "onValueChange = { value -> context.edit(field, value, "
        "model.props.onValueChange, JsonPrimitive(value)) }"
    )
    return {"value", "onValueChange"}
