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

from pycompose.compiler.candidate_props import CandidateError
from pycompose.compiler.check import compare, compare_values
from pycompose.compiler.classpath_dump import (
    ANDROID,
    DUMP_DIR,
    Inventory,
    inventory,
    source_defaults,
    source_drives,
)
from pycompose.compiler.component_binding import spell
from pycompose.compiler.components import propose_components
from pycompose.compiler.entry_candidates import derive, select
from pycompose.compiler.holders import derive as derive_holders
from pycompose.compiler.overloads import extras
from pycompose.compiler.policy import Policy, merge, redundant
from pycompose.compiler.rules import SHAPES, reshape

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
        errors: Refusals that stop the run, stale policy among them.
        overloads: Extra overloads exposed by rule, by name.
        skipped: Extra overloads not exposed, with the reason.
        promoted: Components no policy names, exposed because they derive.
        refused: Components no policy names that do not derive, with the reason.
        coverage: Per artifact group, component overloads by outcome.
    """

    derived: dict[str, int] = field(default_factory=dict)
    manual: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    overloads: list[str] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)
    promoted: list[str] = field(default_factory=list)
    refused: dict[str, str] = field(default_factory=dict)
    coverage: dict[str, dict[str, int]] = field(default_factory=dict)


def promotable(
    plans: dict[str, Any], named: set[str], closure: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    """Review decisions for every component the closure has and no policy names.

    A component is exposed because it derives, never because someone typed it
    in (plan 31 §3.8): its category is its group's domain, it is experimental
    when it needs an opt-in, and of several overloads the one taking the most
    parameters is the primary; the rest follow as overloads. A name whose every
    overload is deprecated is not promoted.

    Args:
        plans: The planner's call plans for the pin.
        named: Native and schema names the catalog already covers.
        closure: The extraction closure, whose groups name each domain.

    Returns:
        Per component name, the decision it derives with.
    """
    domains = {group: spec["domain"] for group, spec in closure["groups"].items()}
    overloads: dict[str, list[dict[str, Any]]] = {}
    for plan in plans["candidates"]:
        if plan["surface"] == "component" and plan["name"] not in named:
            overloads.setdefault(plan["name"], []).append(plan)
    decisions = {}
    for name, found in sorted(overloads.items()):
        current = [
            plan
            for plan in found
            if "kotlin/Deprecated" not in (plan.get("annotations") or {})
        ]
        if not current:
            continue
        usable = [plan for plan in current if plan["status"] == "call-plan"]
        primary = max(
            usable or current,
            key=lambda plan: (len(plan["parameters"]), spell(plan["source"])),
        )
        decision = {
            "category": domains[primary["source"]["artifact"].split(":")[0]],
            "stability": "experimental" if primary["optIn"] else "stable",
        }
        if len(usable) > 1:
            decision["identity"] = spell(primary["source"])
        decisions[name] = decision
    return decisions


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
    unknown = sorted(set(decision) - REVIEW - SHAPES - {"hook"})
    if unknown:
        raise CandidateError(f"{name}: unknown decision keys {unknown}")
    native = decision.get("nativeName", name)
    plan, declaration = select(
        plans,
        found,
        native,
        identity=decision.get("identity"),
        surface="hook" if decision.get("hook") else "component",
    )
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
    found = inventory(directory)
    sections = dict(policy.sections)
    plans = propose_components(found, source_defaults(directory), sections)
    closure = json.loads((ANDROID / "compose-closure.json").read_text(encoding="utf-8"))
    components, report = compile_components(
        policy.components, plans, found, sections, closure
    )
    lock = {**sections, "components": dict(sorted(components.items()))}
    holders, refused = derive_holders(found, source_drives(directory), lock)
    report.errors.extend(refused)
    lock["holders"] = holders
    # What policy keeps -- held entries, value families -- still answers to the pin.
    report.errors.extend(compare(lock, found))
    report.errors.extend(compare_values(lock, found, source_defaults(directory)))
    return {key: lock[key] for key in ORDER if key in lock}, report


def compile_components(
    rules: dict[str, dict[str, Any]],
    plans: dict[str, Any],
    found: Inventory,
    sections: dict[str, Any],
    closure: dict[str, Any],
    taken: frozenset[str] = frozenset(),
) -> tuple[dict[str, Any], Report]:
    """Derive the components policy names, promote the rest, add their overloads.

    Args:
        rules: Per component, its policy: a decision and patch, or a hold.
        plans: The planner's call plans; only these components are compiled.
        found: The pinned inventory.
        sections: The catalog sections the derivation reads.
        closure: The extraction closure.
        taken: Names another catalog already uses: an app's library may not
            promote a component under the library's name.

    Returns:
        The components, and the run's report.
    """
    report = Report()
    components: dict[str, Any] = {}
    for name, rule in sorted(rules.items()):
        if "manual" in rule:
            components[name] = rule["entry"]
            report.manual[name] = rule["manual"]
            if _derives(name, rule["entry"], plans, found, sections):
                report.errors.append(
                    f"{name}: held whole, but the pin derives it; give it a decision"
                )
            continue
        try:
            derived = planned(name, rule["decision"], plans, found, sections)
        except CandidateError as exc:
            report.errors.append(f"{name}: policy says derivable, but {exc}")
            continue
        patch = rule.get("patch", {})
        report.errors.extend(
            f"{name}.{path}: policy the pin already implies"
            for path in redundant(derived, patch)
        )
        components[name] = merge(derived, patch)
        report.derived[name] = len(json.dumps(patch))
    decisions = {
        name: rule["decision"]
        for name, rule in rules.items()
        if "decision" in rule and name in components
    }
    named = set(rules) | {
        entry["source"]["name"] for entry in components.values() if "source" in entry
    }
    for name, decision in promotable(plans, named, closure).items():
        if name in taken:
            report.refused[name] = (
                "the catalog already has this name; name it in policy (nativeName)"
            )
            continue
        try:
            entry = planned(name, decision, plans, found, sections)
        except CandidateError as exc:
            report.refused[name] = str(exc).removeprefix(f"{name}: ")
            continue
        if entry.get("adapter") == "manual":
            # Nobody wrote one, and no policy names it: there is none to register.
            report.refused[name] = "needs a hand-written adapter"
            continue
        components[name] = entry
        decisions[name] = decision
        report.promoted.append(name)
    added, report.skipped = extras(
        components,
        decisions,
        plans,
        lambda name, decision: planned(name, decision, plans, found, sections),
    )
    components.update(added)
    report.overloads = sorted(added)
    report.coverage = _coverage(plans, components)
    return components, report


def _coverage(
    plans: dict[str, Any], components: dict[str, Any]
) -> dict[str, dict[str, int]]:
    """Count every component overload in the closure by group and outcome.

    Every public declaration ends exposed, held or refused (plan 31 §3.6);
    deprecated overloads are counted apart, since none is ever chosen.
    """
    exposed = {
        json.dumps(entry.get("source"), sort_keys=True) for entry in components.values()
    }
    coverage: dict[str, dict[str, int]] = {}
    for plan in plans["candidates"]:
        if plan["surface"] != "component":
            continue
        if json.dumps(plan["source"], sort_keys=True) in exposed:
            outcome = "exposed"
        elif "kotlin/Deprecated" in (plan.get("annotations") or {}):
            outcome = "deprecated"
        else:
            outcome = "refused"
        group = coverage.setdefault(plan["source"]["artifact"].split(":")[0], {})
        group[outcome] = group.get(outcome, 0) + 1
    return dict(sorted(coverage.items()))


def _derives(
    name: str,
    entry: dict[str, Any],
    plans: dict[str, Any],
    found: Inventory,
    sections: dict[str, Any],
) -> bool:
    """Whether a held entry's own overload now derives, making the hold stale.

    A derivation from a different overload does not count: holding a component
    for the overload it binds is a decision, not staleness.
    """
    source = entry.get("source")
    if source is None:
        return False
    decision = {key: entry[key] for key in ("category", "stability")}
    if source["name"] != name:
        decision["nativeName"] = source["name"]
    for attempt in (decision, {**decision, "identity": spell(source)}):
        try:
            derived = planned(name, attempt, plans, found, sections)
            return bool(derived["source"] == source)
        except CandidateError:
            continue
    return False


def dumps(lock: dict[str, Any]) -> str:
    """Serialize the lock canonically.

    Args:
        lock: The lock document.

    Returns:
        Its text, byte-stable for equal content.
    """
    return json.dumps(lock, indent=2, ensure_ascii=False) + "\n"
