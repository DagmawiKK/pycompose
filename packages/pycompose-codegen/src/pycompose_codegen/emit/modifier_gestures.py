"""Kotlin for a gesture modifier: its detector, run inside ``pointerInput``.

A gesture's events dispatch the actions the app bound, an ``Offset`` as the
payload's ``x`` and ``y``; an event left unbound passes the detector's own
default. Its continuous callback adds its deltas into the node's running
totals, which the renderer publishes as streams (``Running.kt``). Positions and
deltas reach the app in dp, as every size it states does; the pointer scope
is a ``Density``, so each is converted where it arrives.
"""

from __future__ import annotations

from typing import Any

from pycompose_codegen.emit.literals import kotlin_string

OFFSET = "androidx.compose.ui.geometry.Offset"


def gesture(name: str, modifier: dict[str, Any]) -> list[str]:
    """The branch of one gesture modifier.

    Args:
        name: The modifier's wire name.
        modifier: Its lock entry.

    Returns:
        The Kotlin lines of its ``when`` branch.
    """
    spec = modifier["gesture"]
    continuous = spec.get("continuous")
    lines = [f"            {kotlin_string(name)} -> {{"]
    if continuous:
        names = ", ".join(kotlin_string(s["name"]) for s in continuous["streams"])
        lines.append(
            "                val running = com.pycompose.renderer.rememberRunning("
            f"node, streams, listOf({names}))"
        )
    detector = spec["detector"].rsplit(".", 1)[-1]
    lines += [
        "                Modifier.pointerInput(op) {",
        f"                    {detector}(",
    ]
    for event, entry in spec["events"].items():
        lines.append(f"                        {event} = {_event(event, entry)},")
    if continuous:
        callback = continuous["callback"]
        lines.append(f"                        {callback} = {_running(continuous)},")
    return [*lines, "                    )", "                }", "            }"]


def _event(event: str, entry: dict[str, Any]) -> str:
    """An event's callback: dispatch the bound action, or the detector's default."""
    if entry["payload"]:
        bound = (
            f"{{ offset: {OFFSET} -> event(id.jsonPrimitive.content, "
            "offsetPayload(offset)) }"
        )
        fallback = "null" if entry["nullable"] else f"{{ _: {OFFSET} -> }}"
    else:
        bound = "{ event(id.jsonPrimitive.content, JsonObject(emptyMap())) }"
        fallback = "null" if entry["nullable"] else "{}"
    return f'op["{event}"]?.let {{ id -> {bound} }} ?: {fallback}'


def _running(continuous: dict[str, Any]) -> str:
    """The continuous callback: add each delta into its running total."""
    arguments = max(s["argument"] for s in continuous["streams"])
    names = ["_", *(f"delta{i}" for i in range(1, arguments + 1))]
    adds = []
    for index, stream in enumerate(continuous["streams"]):
        delta = f"delta{stream['argument']}"
        value = f"{delta}.{stream['axis']}" if "axis" in stream else delta
        adds.append(f"running.add({index}, {value}.toDp().value)")
    return f"{{ {', '.join(names)} -> {'; '.join(adds)} }}"
