"""The schema version each catalog entry and prop entered at.

A derived entry is stamped with the open schema version, which is right only
the first time: the version it entered at is history the pin cannot answer,
so it is read back from the committed lock.
"""

from __future__ import annotations

from typing import Any

VERSIONED = ("components", "modifiers", "valueTypes")
"""Sections whose entries say the schema version they entered at."""


def carried(lock: dict[str, Any], previous: dict[str, Any]) -> None:
    """Keep each entry's ``since`` from the committed lock.

    A derived entry is stamped with the current schema version, which is right
    only the first time: re-stamped at the next bump, every older envelope
    would stop accepting it. The version an entry entered at is history the
    pin cannot answer, so the committed lock is where it is read from. An entry
    the lock already has without one is the first schema's, and stays so.

    Args:
        lock: The lock being generated, changed in place.
        previous: The committed lock.
    """
    for section in VERSIONED:
        known = previous.get(section, {})
        for name, entry in lock.get(section, {}).items():
            if section == "components" and name in known:
                _carried_props(entry, known[name], lock["schemaVersion"])
            if "since" not in entry or name not in known:
                continue
            if "since" in known[name]:
                entry["since"] = known[name]["since"]
            else:
                del entry["since"]


def _carried_props(entry: dict[str, Any], known: dict[str, Any], version: str) -> None:
    """Date each prop as its component is dated: kept if known, current if new.

    A prop the committed lock lacks entered now; without a ``since``, every older
    envelope would claim it.
    """
    previous = known.get("props", {})
    for prop, spec in entry.get("props", {}).items():
        if prop not in previous:
            spec.setdefault("since", version)
        elif "since" in previous[prop]:
            spec["since"] = previous[prop]["since"]
        else:
            spec.pop("since", None)
