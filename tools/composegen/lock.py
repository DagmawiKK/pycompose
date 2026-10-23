"""Assemble the catalog lock from the pinned evidence and the policy overlay.

The stages run in order, each a function of the ones before it: read the pinned
inventory (S1, S2), classify and plan every UI overload (S3), derive each
component the policy names from its call plan (S4), apply the policy (S5), and
derive the holders section from the components and the pinned sources. The
lock is the result: generated, committed, never edited.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tools.composegen.policy import Policy, merge, redundant
from tools.composegen.rules import SHAPES, reshape
from tools.schema.candidate_props import CandidateError
from tools.schema.classpath_dump import (
    DUMP_DIR,
    Inventory,
    inventory,
    source_defaults,
    source_drives,
)
from tools.schema.components import propose_components
from tools.schema.entry_candidates import derive, select
from tools.schema.holders import derive as derive_holders

ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / "schema/catalog.lock.json"

ORDER = (
    "schemaVersion",
    "supportedSchemaVersions",
    "minLibraryVersion",
    "components",
    "modifiers",
    "actions",
    "effects",
    "lifecycle",
    "valueTypes",
    "holders",
)
"""Section order in the lock, so a diff reads the same way every time."""

REVIEW = frozenset({"category", "stability", "nativeName", "identity"})
"""Decision keys the pin cannot answer: what the reviewer chose."""


@dataclass
class Report:
    """What the run found, for review.

    Attributes:
        derived: Components derived from the pin, with their patch size.
        manual: Components held whole by policy, with the reason.
        errors: Refusals that stop the run.
        redundant: Policy entries the derivation already produces.
    """

    derived: dict[str, int] = field(default_factory=dict)
    manual: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    redundant: list[str] = field(default_factory=list)


def planned(
    name: str,
    decision: dict[str, Any],
    plans: dict[str, Any],
    found: Inventory,
    sections: dict[str, Any],
) -> dict[str, Any]:
    """Derive one component's entry from its call plan.

    Args:
        name: The component's schema name.
        decision: The review decisions the pin cannot make.
        plans: The planner's call plans for the pin.
        found: The pinned inventory.
        sections: The catalog sections the derivation reads (value families).

    Returns:
        The derived entry.

    Raises:
        CandidateError: The decision names a key no review or rule reads.
    """
    unknown = sorted(set(decision) - REVIEW - SHAPES)
    if unknown:
        raise CandidateError(f"{name}: unknown decision keys {unknown}")
    native = decision.get("nativeName", name)
    plan, declaration = select(plans, found, native, identity=decision.get("identity"))
    derived = derive(
        plan,
        declaration,
        sections,
        {key: decision[key] for key in REVIEW if key in decision},
        schema_name=name,
    )
    return reshape(name, derived.entry, decision, plan)


def generate(
    policy: Policy, directory: Path = DUMP_DIR
) -> tuple[dict[str, Any], Report]:
    """Run the compiler over the pinned evidence.

    Args:
        policy: The policy overlay.
        directory: Where the pinned evidence was extracted.

    Returns:
        The lock document, and the run's report.
    """
    report = Report()
    found = inventory(directory)
    sections = dict(policy.sections)
    plans = propose_components(found, source_defaults(directory), sections)
    components: dict[str, Any] = {}
    for name, rule in sorted(policy.components.items()):
        if "manual" in rule:
            components[name] = rule["entry"]
            report.manual[name] = rule["manual"]
            continue
        try:
            derived = planned(name, rule["decision"], plans, found, sections)
        except CandidateError as exc:
            report.errors.append(f"{name}: policy says derivable, but {exc}")
            continue
        patch = rule.get("patch", {})
        report.redundant.extend(f"{name}.{path}" for path in redundant(derived, patch))
        components[name] = merge(derived, patch)
        report.derived[name] = len(json.dumps(patch))
    lock = {**sections, "components": components}
    holders, refused = derive_holders(found, source_drives(directory), lock)
    report.errors.extend(refused)
    lock["holders"] = holders
    return {key: lock[key] for key in ORDER if key in lock}, report


def dumps(lock: dict[str, Any]) -> str:
    """Serialize the lock canonically.

    Args:
        lock: The lock document.

    Returns:
        Its text, byte-stable for equal content.
    """
    return json.dumps(lock, indent=2, ensure_ascii=False) + "\n"
