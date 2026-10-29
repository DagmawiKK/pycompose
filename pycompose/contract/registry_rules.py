"""Rules the catalog applies on top of the committed lock."""

from __future__ import annotations

from typing import Any

__all__ = ["WINDOW_PROPS", "with_rules"]

WINDOW_PROPS: dict[str, dict[str, Any]] = {
    "itemCount": {"type": "integer", "minimum": 0, "maximum": 2147483647},
    "itemOffset": {"type": "integer", "minimum": 0, "maximum": 2147483647},
    "window": {"type": "string"},
}
"""What a lazy container states so the host can ask for a window of it (ADR-0043)."""


def with_rules(registry: dict[str, Any]) -> dict[str, Any]:
    """Apply the catalog's rules: every lazy container gets windowing's props.

    A lazy container states how many items it has, the index of the first one
    it composed, and the key the host asks for windows by. These are protocol,
    not native parameters, so they are marked as such and no adapter passes
    them on and no Python signature offers them.

    Args:
        registry: The catalog, extended in place.

    Returns:
        The same catalog, for chaining.
    """
    for entry in registry.get("components", {}).values():
        if entry.get("children", {}).get("kind") == "items":
            for name, prop in WINDOW_PROPS.items():
                entry.setdefault("props", {}).setdefault(
                    name, {**prop, "protocol": "window"}
                )
    return registry
