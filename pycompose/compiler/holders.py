"""Derive each state holder's drive table from pinned source evidence (plan 30 §4).

A drive moves a native holder to one anchor of its value enum. For each anchor
the table names exactly one public, non-deprecated suspend member: a member
without parameters whose pinned body targets that constant anchor, else the one
member taking only the anchor that hands it to an animating primitive. A holder
with no anchor drives is not recorded; one whose anchors are not all covered is
refused by name, never completed by a guess.
"""

from __future__ import annotations

from typing import Any

from pycompose.compiler.classpath_dump import Inventory, opt_in_index, required_opt_ins
from pycompose.compiler.classpath_types import Declaration

ANIMATING = frozenset({"androidx.compose.foundation.gestures.animateTo"})
"""Primitive drives that animate rather than snap: approved policy (plan 30 §4.3)."""

Key = tuple[str, str, str]


def derive(
    found: Inventory, drives: dict[Key, dict[str, Any]], registry: dict[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    """Derive the ``holders`` catalog section the pin implies.

    Args:
        found: The validated inventory of the current pin.
        drives: Drive evidence keyed by JVM identity (``source_drives``).
        registry: The approved catalog, whose stateful components name holders.

    Returns:
        The section keyed by holder class, and one message per refused holder.
    """
    members = {
        (d.owner, d.jvm_name or "", d.jvm_descriptor or ""): d
        for d in found.declarations
    }
    index = opt_in_index(found)
    holders: dict[str, Any] = {}
    errors: list[str] = []
    for holder in sorted(_holders(members, registry)):
        evidence = [
            (members[key], drive)
            for key, drive in drives.items()
            if key[0] == holder
            and key in members
            and drive["kind"] != "unknown"
            and "kotlin/Deprecated" not in members[key].annotations
        ]
        if not evidence:
            continue
        value, table, missing = _table(found, evidence)
        if missing:
            errors.append(f"{holder}: no unique drive for {', '.join(missing)}")
            continue
        markers = {m for d in table.values() for m in required_opt_ins(d, index)}
        holders[holder] = {
            "value": value,
            "optIn": sorted(markers),
            "drives": {
                anchor: {"method": d.name, **({"anchor": True} if d.parameters else {})}
                for anchor, d in table.items()
            },
        }
    return holders, errors


def _holders(members: dict[Key, Declaration], registry: dict[str, Any]) -> set[str]:
    """Native holder classes the catalog's stateful components take."""
    found = set()
    for entry in registry["components"].values():
        state, source = entry.get("state"), entry.get("source")
        if state is None or source is None:
            continue
        declaration = members.get(
            (source["owner"], source["jvmName"], source["descriptor"])
        )
        if declaration is None:
            continue
        for parameter in declaration.parameters:
            if parameter.name == state["native"]:
                found.add(parameter.type.classifier.replace("/", "."))
    return found


def _table(
    found: Inventory, evidence: list[tuple[Declaration, dict[str, Any]]]
) -> tuple[str, dict[str, Declaration], list[str]]:
    """Choose one drive per anchor of the holder's single value enum."""
    enums = {
        drive["anchor"].rsplit(".", 1)[0]
        if drive["kind"] == "constant"
        else d.parameters[0].type.classifier.replace("/", ".")
        for d, drive in evidence
    }
    if len(enums) != 1:
        return "", {}, [f"{len(enums)} value enums"]
    value = enums.pop()
    entries = next(
        (
            c.document.get("enumEntries") or []
            for c in found.classes
            if c.classifier == value
        ),
        [],
    )
    table: dict[str, Declaration] = {}
    missing: list[str] = []
    for entry in entries:
        constant = [
            d
            for d, drive in evidence
            if drive["kind"] == "constant"
            and drive["anchor"] == f"{value}.{entry}"
            and not d.parameters
        ]
        passing = [
            d
            for d, drive in evidence
            if drive["kind"] == "parameter"
            and len(d.parameters) == 1
            and drive["callee"] in ANIMATING
        ]
        picked = constant or passing
        if len(picked) == 1:
            table[entry] = picked[0]
        else:
            missing.append(entry)
    return value, table, missing or ([] if entries else ["enum entries"])
