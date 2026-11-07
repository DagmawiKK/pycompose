"""Text fields that keep what was typed until Python has answered it."""

from __future__ import annotations

from typing import Any

from pycompose_codegen.emit.adapters.fragments import Fragments

__all__ = ["CARET_IMPORTS", "EDIT_IMPORTS", "echoed_text", "echoes", "follows_caret"]

EDIT_IMPORTS = frozenset(
    {"com.pycompose.renderer.edit", "com.pycompose.renderer.edited"}
)
"""The renderer's reconciler, which a reconciled field calls."""

CARET_IMPORTS = frozenset(
    {
        "androidx.compose.ui.text.input.TextFieldValue",
        "com.pycompose.renderer.editText",
        "com.pycompose.renderer.editedText",
    }
)
"""The reconciler over text and caret, which a field the app may place calls."""


def follows_caret(props: dict[str, Any]) -> bool:
    """Whether a reconciled text field also lets the app state its caret.

    Args:
        props: The component's declared props, by wire name.

    Returns:
        True for an optional integer ``selection`` and its ``onSelectionChange``.
    """
    caret, change = props.get("selection") or {}, props.get("onSelectionChange") or {}
    reported = [(f["name"], f["type"]) for f in change.get("payload") or []]
    return (
        echoes(props)
        and caret.get("type") == "integer"
        and change.get("type") == "actionId"
        and reported == [("value", "integer")]
    )


def echoes(props: dict[str, Any]) -> bool:
    """Whether a component is a text field whose value comes back as its text.

    Args:
        props: The component's declared props, by wire name.

    Returns:
        True for a required string and its ``on<Name>Change`` report of it.
    """
    return echoed_pair(props) is not None


def echoed_pair(props: dict[str, Any]) -> tuple[str, str] | None:
    """The text a field shows and the report it comes back by: ``value`` and
    ``onValueChange``, or a search field's ``query`` and ``onQueryChange``.

    Args:
        props: The component's declared props, by wire name.

    Returns:
        The two prop names, or None when the component has no such pair.
    """
    for name in sorted(props, key=lambda n: n != "value"):
        value = props[name]
        change_name = f"on{name[:1].upper()}{name[1:]}Change"
        change = props.get(change_name) or {}
        reported = [(f["name"], f["type"]) for f in change.get("payload") or []]
        if (
            value.get("type") == "string"
            and bool(value.get("required"))
            and change.get("type") == "actionId"
            and bool(change.get("required"))
            and reported == [(name, "string")]
        ):
            return name, change_name
    return None


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
    pair = echoed_pair(props)
    if pair is None:
        return set()
    name, change = pair
    if name == "value" and follows_caret(props):
        # The text and the caret travel as one native value, whose overload the
        # call then resolves to; the app's caret stands once it has answered.
        out.locals.append(
            "val field = context.editedText(model.id, model.props.value, "
            "model.props.selection, model.props.onValueChange, "
            "model.props.onSelectionChange)"
        )
        out.arguments.append("value = field.value")
        out.arguments.append(
            "onValueChange = { value: TextFieldValue -> context.editText(field, value, "
            "model.props.onValueChange, model.props.onSelectionChange) }"
        )
        return {"value", "onValueChange", "selection", "onSelectionChange"}
    out.locals.append(
        f"val field = context.edited(model.id, model.props.{name}, "
        f"model.props.{change})"
    )
    out.arguments.append(f"{name} = field.value")
    out.arguments.append(
        f"{change} = {{ value -> context.edit(field, value, "
        f"model.props.{change}, JsonPrimitive(value)) }}"
    )
    return {name, change}
