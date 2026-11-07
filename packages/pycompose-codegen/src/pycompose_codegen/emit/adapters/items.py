"""Item components: builder members the host applies, never composes.

``AppBarScope.clickableItem`` is called inside ``AppBarRow``'s builder, a plain
lambda: the adapter is one too, registered for its scope and run on the
builder's receiver for each child the app sends. Nothing outside composition
may remember or resolve through composition, so an item passes only what
needs neither: scalars, sizes, callbacks, and its composable slots, which
compose later wherever the parent places them.
"""

from __future__ import annotations

from typing import Any

from pycompose_codegen.emit.adapters.fragments import Fragments
from pycompose_codegen.emit.adapters.policy import simple

ITEM_TYPES = frozenset(
    {"string", "boolean", "integer", "number", "dp", "actionId", "modifier"}
)
"""Prop types an item renders with no remembered or composition-read value."""

HELD = ("state", "holders", "interaction", "transient", "built", "shared")
"""Entry facts whose host values are remembered in composition: none fits an item."""


def indented(argument: str, indent: str) -> str:
    """An argument spanning lines, its later lines under its first."""
    return argument.replace("\n", f"\n{indent}    ")


def item_ready(entry: dict[str, Any]) -> bool:
    """Whether an item's adapter can run outside composition."""
    return item_refusal(entry) is None


def item_refusal(entry: dict[str, Any]) -> str | None:
    """What an item would need composed, or None when it needs nothing."""
    held = [fact for fact in HELD if entry.get(fact)]
    held += [
        prop
        for prop, spec in entry.get("props", {}).items()
        if spec["type"] not in ITEM_TYPES or "provider" in spec or spec.get("content")
    ]
    if not held:
        return None
    needed = ", ".join(held)
    return f"an item is applied outside composition, where {needed} cannot be"


def render_item(name: str, entry: dict[str, Any], out: Fragments, call: str) -> str:
    """Register an item's adapter: its member called on the builder's receiver.

    Args:
        name: The component's schema name.
        entry: Its schema entry, an item (``item_ready``).
        out: The rendered locals and arguments, without a modifier.
        call: The member's name.

    Returns:
        The registration as Kotlin.
    """
    indent = "                "
    prelude = "".join(f"{indent}{line}\n" for line in out.locals)
    arguments = "".join(
        f"{indent}    {indented(argument, indent)},\n" for argument in out.arguments
    )
    return (
        f"            .registerItem<{simple(entry['scope'])}>"
        f'("{name}") {{ node, context ->\n'
        f"{indent}val model = node as {name}Node\n"
        f"{prelude}{indent}{call}(\n{arguments}{indent})\n"
        "            }"
    )
