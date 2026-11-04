"""A hand-written adapter reads every prop its component offers Python.

A generated adapter passes each prop by construction; a hand-written one passes
what its author wrote. A prop the catalog offers and no adapter reads would be
accepted in Python and dropped on the phone, so policy refuses it, with that
reason, until its adapter reads it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "schema/catalog.lock.json"
HAND = (
    ROOT / "android/host/src/main/kotlin/com/pycompose/host/ui",
    ROOT / "android/renderer/src/main/kotlin/com/pycompose/renderer",
)


def _hand_source() -> str:
    return "".join(
        path.read_text(encoding="utf-8")
        for folder in HAND
        for path in sorted(folder.glob("*.kt"))
        if not path.name.startswith("Generated")
    )


def test_every_prop_of_a_hand_adapted_component_is_read() -> None:
    components = json.loads(LOCK.read_text(encoding="utf-8"))["components"]
    source = _hand_source()
    hand = {
        name: entry
        for name, entry in components.items()
        if entry.get("adapter") == "manual"
    }
    assert hand
    unread = {
        name: sorted(
            prop
            for prop in entry["props"]
            if prop != "modifier" and not re.search(rf"\.{prop}\b", source)
        )
        for name, entry in hand.items()
    }
    assert {name: props for name, props in unread.items() if props} == {}
