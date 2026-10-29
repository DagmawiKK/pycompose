"""Text fields that keep what was typed while Python's echo is in flight."""

from __future__ import annotations

from typing import Any

from pycompose.codegen.adapter_helpers import _Fragments

__all__ = ["echoed_text"]


def echoed_text(props: dict[str, Any], out: _Fragments) -> set[str]:
    """Render a text field's value through the host's echo of what was typed.

    A field that showed each snapshot's text would apply the next keystroke to
    text one or more keys old, so keys typed faster than Python echoes them
    would be lost. A field whose text value is reported back as text shows the
    latest keystroke instead, until the app states text of its own
    (``EchoedText``, shared with the host's hand-written fields).

    Args:
        props: The component's declared props, by wire name.
        out: Collects the rendered pieces.

    Returns:
        The props rendered here, or none for a component of another shape.
    """
    value, change = props.get("value") or {}, props.get("onValueChange") or {}
    reported = [(f["name"], f["type"]) for f in change.get("payload") or []]
    if not (
        value.get("type") == "string"
        and value.get("required")
        and change.get("type") == "actionId"
        and change.get("required")
        and reported == [("value", "string")]
    ):
        return set()
    out.locals.append("val echoed = rememberEchoedText(model.id, model.props.value)")
    out.arguments.append("value = echoed.text")
    out.arguments.append(
        "onValueChange = { value -> echoed.typed(value); "
        "context.event(model.props.onValueChange, JsonPrimitive(value)) }"
    )
    return {"value", "onValueChange"}
