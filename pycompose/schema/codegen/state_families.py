"""The wire projection each host state family owns (plan 31 §5, holder binding).

A family is one host implementation (see ``STATE_KINDS``); it decides what the
app states and what it hears back, whatever component binds it. A drawer's
desired state is ``open`` and its settled report ``onOpenChange``, in
``ModalNavigationDrawer`` and ``DismissibleNavigationDrawer`` alike. A family
may also hold props its holder is built from (a slider's range and steps);
the adapter passes those to the holder, never to the component.

The compiler projects these props onto every component the pin binds to a
family, and codegen reads the held props from here, so neither keeps a copy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pycompose.schema.codegen.state_anchors import SHEET_VALUES, SWIPE_VALUES

_INT = 2**31 - 1
_SELECTION: dict[str, dict[str, Any]] = {
    "selectionStart": {
        "type": "integer",
        "required": True,
        "minimum": 0,
        "maximum": _INT,
        "nativeType": "Int",
    },
    "selectionEnd": {
        "type": "integer",
        "required": True,
        "minimum": 0,
        "maximum": _INT,
        "nativeType": "Int",
    },
    "revision": {
        "type": "integer",
        "required": True,
        "minimum": 0,
        "maximum": 2**63 - 1,
    },
}
_EDIT = {
    "type": "actionId",
    "required": True,
    "payload": [
        {"name": "text", "type": "string"},
        {"name": "selectionStart", "type": "integer"},
        {"name": "selectionEnd", "type": "integer"},
        {"name": "revision", "type": "integer"},
    ],
}


@dataclass(frozen=True)
class Family:
    """One family's projection.

    Attributes:
        value: The prop carrying the app's desired state, and its spec.
        report: The prop reporting the settled state; it carries one field
            named after the value unless ``reported`` says otherwise.
        reported: The report's own spec, for a family whose report is richer.
        held: Props the holder is built from, in the order the renderer takes.
        shared: Whether the host shares one owner with nested declarations (a
            search's text and bar state reach its input field), which only a
            hand-written adapter composes.
    """

    value: tuple[str, dict[str, Any]]
    report: str
    reported: dict[str, Any] | None = None
    held: dict[str, dict[str, Any]] = field(default_factory=dict)
    shared: bool = False

    def props(self) -> dict[str, dict[str, Any]]:
        """Every prop the family projects: value, report, then held props.

        Returns:
            Wire props by name.
        """
        name, spec = self.value
        kind = "string" if spec["type"] == "enum" else spec["type"]
        report = self.reported or {
            "type": "actionId",
            "payload": [{"name": name, "type": kind}],
        }
        return {name: spec, self.report: report, **self.held}


STATE_FAMILIES: dict[str, Family] = {
    "drawer": Family(("open", {"type": "boolean"}), "onOpenChange"),
    "sheet": Family(
        ("open", {"type": "boolean"}),
        "onOpenChange",
        held={
            "value": {"type": "enum", "values": list(SHEET_VALUES)},
            "onValueChange": {
                "type": "actionId",
                "payload": [{"name": "value", "type": "string"}],
            },
            "skipPartiallyExpanded": {"type": "boolean", "default": False},
        },
    ),
    "slider": Family(
        ("value", {"type": "number"}),
        "onValueChangeFinished",
        held={
            "valueRange": {"type": "value", "valueType": "Range", "required": True},
            "steps": {
                "type": "integer",
                "default": 0,
                "minimum": 0,
                "maximum": _INT - 2,
            },
        },
    ),
    "scroll": Family(("offset", {"type": "number"}), "onScrollIdle"),
    "lazyList": Family(
        ("firstVisibleIndex", {"type": "integer", "minimum": 0, "maximum": _INT}),
        "onScrollIdle",
    ),
    "tooltip": Family(
        ("visible", {"type": "boolean"}),
        "onVisibilityChange",
        held={"isPersistent": {"type": "boolean", "default": False}},
    ),
    "textInput": Family(
        ("text", {"type": "string", "required": True}),
        "onEdit",
        reported=_EDIT,
        held=_SELECTION,
    ),
    "search": Family(
        ("expanded", {"type": "boolean"}),
        "onExpandedChange",
        held={
            "text": {"type": "string", "required": True},
            **_SELECTION,
            "onEdit": _EDIT,
        },
        shared=True,
    ),
    "swipe": Family(
        ("value", {"type": "enum", "values": list(SWIPE_VALUES)}), "onValueChange"
    ),
}
"""Every state family's projection, keyed like ``STATE_KINDS``."""

TRANSIENT_FAMILIES: dict[str, dict[str, Any]] = {
    "snackbar": {
        "props": {
            "message": {"type": "string", "required": True},
            "actionLabel": {"type": "string"},
            "serial": {"type": "integer", "required": True},
            "onDismiss": {
                "type": "actionId",
                "payload": [{"name": "serial", "type": "integer"}],
            },
        },
        "serial": "serial",
        "occurrence": "onDismiss",
    },
}
"""Each transient family's projection: its props, the serial and the occurrence."""
