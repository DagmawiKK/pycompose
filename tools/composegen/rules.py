"""Reshape rules: the pin decides how, once policy names the shape it wants.

Two shapes recur across the catalog. ``flatten`` turns a content slot whose
idiomatic use is one ``Text`` into a string prop; ``observe`` reports the
press, focus and hover the native interaction source emits. Which components
take them is a review decision, kept in policy as one word each; which
parameter, which props and which payloads follow from the pin.

A holder the pin binds always takes its family's projection (state_families);
``holder: false`` declines a defaulted one the component keeps to itself.
"""

from __future__ import annotations

import copy
from typing import Any

from pycompose.core.registry_vocabulary import INTERACTION_KINDS, INTERACTION_REPORTS
from pycompose.schema.codegen.state_families import STATE_FAMILIES
from tools.schema.candidate_props import CandidateError

INTERACTION_SOURCE = "androidx/compose/foundation/interaction/MutableInteractionSource"
SHAPES = frozenset({"flatten", "observe", "holder"})
"""Decision keys these rules read."""


def reshape(
    name: str, entry: dict[str, Any], decision: dict[str, Any], plan: dict[str, Any]
) -> dict[str, Any]:
    """Apply the shapes a decision names to a derived entry.

    Args:
        name: The component's schema name, for refusals.
        entry: The derived entry; not modified.
        decision: The component's policy decision.
        plan: The call plan the entry was derived from.

    Returns:
        The reshaped entry; a shape the pin cannot carry raises
        ``CandidateError``.
    """
    entry = copy.deepcopy(entry)
    invented: list[str] = []
    for native in decision.get("flatten", ()):
        invented.extend(_flatten(name, entry, native, plan))
    if decision.get("observe"):
        invented.extend(_observe(name, entry, plan))
    if decision.get("holder") is False:
        # A defaulted holder the component keeps to itself: nothing to bind.
        entry.pop("state", None)
    elif "state" in entry:
        invented.extend(_project(entry))
    if invented:
        # Props Compose's signature has no counterpart for, so the drift
        # checker reads them as deliberate.
        entry["reshaped"] = invented
    return entry


def _flatten(
    name: str, entry: dict[str, Any], native: str, plan: dict[str, Any]
) -> list[str]:
    """Replace a content slot with a string its adapter renders with ``Text``."""
    spec = plan["parameters"].get(native)
    if spec is None or spec["policy"] != "slot":
        raise CandidateError(f"{name}: flatten names {native!r}, which is no slot")
    slots = entry.get("slots", {})
    if native in slots:
        del slots[native]
        if not slots:
            del entry["slots"]
        prop, content = native, {"composable": "Text", "parameter": native}
    else:
        # The primary content: Compose names it after its role, the wire after
        # what it carries.
        entry["children"] = {"allowed": False}
        prop, content = "text", {"composable": "Text"}
    entry["props"][prop] = {
        "type": "string",
        **({"required": True} if spec["required"] else {}),
        "content": content,
    }
    return [prop] if prop != native else []


def _project(entry: dict[str, Any]) -> list[str]:
    """Give a bound holder its family's props: desired value, report, held."""
    family = STATE_FAMILIES[entry["state"]["kind"]]
    projected = family.props()
    entry["props"].update(copy.deepcopy(projected))
    entry["state"].update({"value": family.value[0], "report": family.report})
    return list(projected)


def _observe(name: str, entry: dict[str, Any], plan: dict[str, Any]) -> list[str]:
    """Report the interaction source's press, focus and hover as actions."""
    sources = [
        parameter
        for parameter, spec in plan["parameters"].items()
        if spec["type"]["classifier"] == INTERACTION_SOURCE
    ]
    if len(sources) != 1:
        raise CandidateError(f"{name}: observe needs one interaction source")
    observations = {kind: "on" + kind.capitalize() for kind in INTERACTION_KINDS}
    for kind, prop in observations.items():
        entry["props"][prop] = {
            "type": "actionId",
            "payload": [{"name": INTERACTION_REPORTS[kind], "type": "boolean"}],
        }
    entry["interaction"] = {"native": sources[0], "observations": observations}
    return list(observations.values())
