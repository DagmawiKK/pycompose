"""Derive each state holder's drive table from pinned source evidence.

A drive moves a native holder to one anchor of its value enum. For each anchor
the table names exactly one public, non-deprecated suspend member: a member
without parameters whose pinned body targets that constant anchor, else the one
member taking only the anchor that hands it to an animating primitive. A holder
with no anchor drives is not recorded; one whose anchors are not all covered is
refused by name, never completed by a guess.
"""

from __future__ import annotations

from typing import Any

from pycompose_codegen.derive.classpath_dump import Inventory
from pycompose_codegen.derive.classpath_types import Declaration
from pycompose_codegen.derive.opt_ins import opt_in_index, required_opt_ins

ANIMATING = frozenset({"androidx.compose.foundation.gestures.animateTo"})
"""Primitive drives that animate rather than snap: approved policy."""

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


def anchored_holders(
    found: Inventory, drives: dict[Key, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Every holder the pin lets the host's anchored runtime create and drive.

    A holder qualifies on its own evidence, whichever component takes it: drives
    covering every anchor of its value enum, a factory starting at an anchor,
    and a settled anchor to read back.

    Args:
        found: The validated inventory of the current pin.
        drives: Drive evidence keyed by JVM identity (``source_drives``).

    Returns:
        Per holder, by slash classifier: its class, value enum and anchors (as
        the wire spells them), factory, settled member, and whether the factory
        has its own start, so the app may leave the value unstated.
    """
    members = {
        (d.owner, d.jvm_name or "", d.jvm_descriptor or ""): d
        for d in found.declarations
    }
    holders = {}
    for holder in sorted({key[0] for key in drives}):
        evidence = [
            (members[key], drive)
            for key, drive in drives.items()
            if key[0] == holder
            and key in members
            and drive["kind"] != "unknown"
            and "kotlin/Deprecated" not in members[key].annotations
        ]
        value, table, missing = (
            _table(found, evidence) if evidence else ("", {}, ["drives"])
        )
        anchored = None if missing else _anchored(found, holder, value)
        if anchored is None:
            continue
        factory = next(
            d
            for d in found.declarations
            if f"{d.package}.{d.name}" == anchored["factory"]
            and d.document.get("category") == "composable-factory"
        )
        start = next(p for p in factory.parameters if p.name == "initialValue")
        holders[holder.replace(".", "/")] = {
            "holder": holder,
            "valueClass": value,
            "anchors": {entry[:1].lower() + entry[1:]: entry for entry in table},
            "factory": anchored["factory"],
            "settled": anchored["settled"],
            **({"started": True} if start.has_default else {}),
        }
    return holders


def _anchored(found: Inventory, holder: str, value: str) -> dict[str, str] | None:
    """How a holder is created at an anchor and read back, when the pin says.

    The factory is the one current composable factory taking ``initialValue``
    of the value enum with every other parameter defaulted; the settled anchor
    is ``settledValue`` where the holder has one, else ``currentValue``. A
    holder lacking either is no anchored holder.
    """
    slashed = holder.replace(".", "/")
    enum = value.replace(".", "/")
    factories = [
        d
        for d in found.declarations
        if d.document.get("category") == "composable-factory"
        and d.return_type.classifier == slashed
        and "kotlin/Deprecated" not in d.annotations
        and any(
            p.name == "initialValue" and p.type.classifier == enum for p in d.parameters
        )
        and all(p.has_default or p.name == "initialValue" for p in d.parameters)
    ]
    readable = {
        d.name
        for d in found.declarations
        if d.owner == holder
        and d.document.get("declarationKind") == "property"
        and d.document.get("visibility") == "PUBLIC"
        and d.return_type.classifier == enum
    }
    settled = next((n for n in ("settledValue", "currentValue") if n in readable), None)
    if len(factories) != 1 or settled is None:
        return None
    factory = factories[0]
    return {"factory": f"{factory.package}.{factory.name}", "settled": settled}


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
