"""Native parameters the host fills: built by the pin's one builder, or shared.

``TooltipBox(positionProvider = ...)`` takes a ``PopupPositionProvider``, which
the app cannot state; the pin's one builder makes it from a value the app can,
``TooltipDefaults.rememberTooltipPositionProvider(positioning)``. The adapter
reads the builder's arguments as it reads any prop, then passes the call.
"""

from __future__ import annotations

from typing import Any

from pycompose_codegen.emit.adapters.fragments import Fragments
from pycompose_codegen.emit.adapters.props import render_prop


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


def shared_arguments(entry: dict[str, Any], out: Fragments) -> None:
    """Pass each shared parameter the holder of the node the app names.

    An expanded search bar uses its bar's ``SearchBarState``: the app names the
    bar's node, and until that node has composed, this one waits.

    Args:
        entry: The component's schema entry.
        out: Collects the rendered pieces.
    """
    label = "registerScoped" if entry.get("scope") else "register"
    for native, holder in sorted(entry.get("shared", {}).items()):
        out.locals.append(
            f"val {native}Shared = context.shared<{holder}>(model.props.{native}) "
            f"?: return@{label}"
        )
        out.arguments.append(f"{native} = {native}Shared")
