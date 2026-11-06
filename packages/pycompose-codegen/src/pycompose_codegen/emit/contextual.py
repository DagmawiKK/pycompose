"""Native calls whose defaults come from their own context.

A family's factory may default a parameter to something the default vocabulary
cannot spell -- ``lightColorScheme``'s internal palette tokens -- or to another
of its parameters (``surfaceTint = primary``). The first is read back from the
same call made with no arguments, whose result exposes it under the parameter's
name; the second is that argument, so what the app states carries as the
factory would carry it.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

CONTEXTUAL = frozenset({"base", "parameter"})
"""Defaults read from the call's own context: the bare call, or another argument."""


def contextual(
    name: str,
    spec: dict[str, Any],
    defaults: dict[tuple[str, str], str],
    decode: Callable[[str, dict[str, Any]], str],
) -> list[str]:
    """A call whose defaults come from its context, each argument a local in order.

    A default the vocabulary cannot render is read back from the call made with
    no arguments (``lightColorScheme().primary``); one naming an earlier
    argument is that argument (``surfaceTint = primary``), so a stated primary
    tints the surface as the factory itself would.
    """
    call = spec["native"]["call"]
    lines = []
    if any(
        r.get("default", {}).get("kind") == "base" for r in spec["parameters"].values()
    ):
        lines.append(f"                val base = {call}()")
    for field, rule in spec["parameters"].items():
        source = f"value.{field}"
        if rule.get("required") and not rule.get("nullable"):
            lines.append(f"                val {field} = {decode(source, rule)}")
            continue
        converted = decode("item", rule)
        present = f"{source}?.let {{ item -> {converted} }}" + (
            "" if rule.get("nullable") else "!!"
        )
        default = rule.get("default", {})
        fallback = {
            "base": f"base.{field}",
            "parameter": str(default.get("name")),
        }.get(default.get("kind"), defaults.get((name, field), "null"))
        lines.append(
            f'                val {field} = if ("{field}" in value.supplied) '
            f"{present} else {fallback}"
        )
    lines.append(f"                {call}(")
    lines.extend(
        f"                    {field} = {field}," for field in spec["parameters"]
    )
    lines.append("                )")
    return lines
