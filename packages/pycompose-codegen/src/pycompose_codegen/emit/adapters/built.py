"""Native parameters the host builds with the pin's one builder for their type.

``TooltipBox(positionProvider = ...)`` takes a ``PopupPositionProvider``, which
the app cannot state; the pin's one builder makes it from a value the app can,
``TooltipDefaults.rememberTooltipPositionProvider(positioning)``. The adapter
reads the builder's arguments as it reads any prop, then passes the call.
"""

from __future__ import annotations

from typing import Any

from pycompose_codegen.emit.adapters.fragments import Fragments
from pycompose_codegen.emit.adapters.props import render_prop


def built_props(entry: dict[str, Any]) -> set[str]:
    """The props a builder consumes, which name no parameter of the component.

    Args:
        entry: The component's schema entry.

    Returns:
        Their names.
    """
    return {
        argument
        for spec in entry.get("built", {}).values()
        for argument in spec["arguments"]
    }


def built_arguments(
    entry: dict[str, Any],
    out: Fragments,
    converters: dict[str, dict[str, Any]],
) -> bool:
    """Pass each built parameter its builder's call, its arguments read as props.

    Args:
        entry: The component's schema entry.
        out: Collects the rendered pieces.
        converters: The lock's animation converters, by Kotlin type.

    Returns:
        False when an argument cannot be read, and the adapter is abandoned.
    """
    for native, spec in sorted(entry.get("built", {}).items()):
        read = Fragments()
        for argument in spec["arguments"]:
            if not render_prop(argument, entry["props"][argument], read, converters):
                return False
        out.locals.extend(read.locals)
        out.arguments.append(
            f"{native} = {spec['factory']}({', '.join(read.arguments)})"
        )
    return True
