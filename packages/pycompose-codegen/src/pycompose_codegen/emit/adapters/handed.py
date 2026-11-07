"""Holders a slot is handed, projected onto the slot's owner.

A slot lambda handed a holder its owner creates (``overflowIndicator:
@Composable (AppBarMenuState) -> Unit``) carries, in the catalog, the property
the holder's bare members set and which member sets each value. The app
states the property; inside the lambda the host calls the member that sets
what the app asked for, and reports a change the holder makes itself.
"""

from __future__ import annotations

from typing import Any


def handed_channels(entry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The children block and named slots handed a holder, by native parameter."""
    channels = [entry.get("children", {}), *entry.get("slots", {}).values()]
    return {
        channel.get("native", "content"): channel
        for channel in channels
        if channel.get("handed")
    }


def report_prop(value: str) -> str:
    """The event reporting a handed property's change: ``onIsExpandedChange``."""
    return f"on{value[:1].upper()}{value[1:]}Change"


def handed_props(entry: dict[str, Any]) -> list[str]:
    """The props a handed holder projects: its property, then the report."""
    return [
        prop
        for channel in handed_channels(entry).values()
        for prop in (
            channel["handed"]["value"],
            report_prop(channel["handed"]["value"]),
        )
    ]


def handed_call(handed: dict[str, Any]) -> str:
    """Reconcile the holder a lambda is handed (``holder``) with its owner's props.

    A change of the stated value calls the member that sets it; a change the
    holder makes itself (a dismissing tap) is reported once.
    """
    value = handed["value"]
    drives = handed["drives"]
    drive = f"if (it) holder.{drives['true']}() else holder.{drives['false']}()"
    return (
        f'context.reconcileProperty(holder, "{value}", '
        f"model.props.{value}?.let(::Wanted), model.props.{report_prop(value)}, "
        f"{{ holder.{value} }}, {{ {drive} }}) {{ JsonPrimitive(it) }}"
    )


HANDED_IMPORTS = frozenset(
    {"com.pycompose.renderer.Wanted", "com.pycompose.renderer.reconcileProperty"}
)
"""What a handed holder's reconciliation names."""
