"""Derive candidate component entries from fresh planner call plans.

The planner says how exactly one pinned overload would be called; this module
turns that plan into a candidate registry entry:

* identity comes from the pin -- one plan, one declaration, recorded ``source``
* declarations and defaults come from the plan: props, payloads, slots and the
  compiler-resolved default expressions a closed wire can carry
* taxonomy the pin cannot decide (``category``, ``stability``, ``since``) is
  review input from a decisions file and is refused when missing

A candidate is never the approved schema. ``--out`` stages an isolated copy of
the catalog with the derived entries inserted; stale plans, ambiguous
overloads, already-approved names and entries the production emitters refuse
all stop the run before anything is written. Applying the reviewed copy stays
a human act: this tool only ever reads the approved schema.

    python tools/schema/entry_candidates.py AssistChip Badge \\
        --decisions candidates-decisions.json \\
        --out android/build/compose-api/candidate-registry.json \\
        --review android/build/compose-api/candidate-review.json --summary
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if __package__ in (None, ""):  # pragma: no cover - only when run as a script
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tools.schema.candidate_props import (
    CandidateError,
    family_index,
    wire_shape,
)
from tools.schema.classpath_dump import DUMP_DIR, Declaration, Inventory, inventory
from tools.schema.component_binding import identity, resolutions, spell


@dataclass(frozen=True)
class Derived:
    """One derived candidate entry and the differences a reviewer reads.

    Attributes:
        name: The component's schema name.
        entry: The candidate registry entry, derived from the pin.
        review: Compatibility differences between the native call and the wire.
    """

    name: str
    entry: dict[str, Any]
    review: tuple[str, ...]


def dumps(document: dict[str, Any]) -> str:
    """Serialize a staged document the way the approved schema is stored."""
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def check_fresh(plans: dict[str, Any], found: Inventory) -> None:
    """Refuse a plan document that was not derived from the pinned inventory.

    Args:
        plans: The planner's output document.
        found: The validated inventory of the current pin.

    Raises:
        CandidateError: The document predates or postdates the pin.
    """
    if plans.get("formatVersion") != 1:
        raise CandidateError(
            f"plans: unsupported formatVersion {plans.get('formatVersion')!r}"
        )
    if plans.get("bom") != found.bom or plans.get("compiler") != found.compiler:
        raise CandidateError(
            f"plans: derived from bom {plans.get('bom')!r} / compiler "
            f"{plans.get('compiler')!r}; the inventory is {found.bom!r} / "
            f"{found.compiler!r}"
        )


def select(
    plans: dict[str, Any], found: Inventory, name: str
) -> tuple[dict[str, Any], Declaration]:
    """Select the one call plan and declaration behind a component name.

    Args:
        plans: The fresh planner output.
        found: The validated inventory of the current pin.
        name: The component's schema name.

    Returns:
        The selected call plan and the pinned declaration it records.

    Raises:
        CandidateError: The name has no single representable call plan.
    """
    matches = [
        candidate
        for candidate in plans["candidates"]
        if candidate["name"] == name and candidate["surface"] == "component"
    ]
    usable = [candidate for candidate in matches if candidate["status"] == "call-plan"]
    if not usable:
        reasons: set[str] = set()
        for candidate in matches:
            for gap in candidate.get("gaps", ()):
                reason = gap.get("reason")
                if gap.get("required") and isinstance(reason, str):
                    reasons.add(reason)
        detail = f": {', '.join(sorted(reasons))}" if reasons else ""
        raise CandidateError(f"{name}: no call plan in the pinned inventory{detail}")
    if len(usable) > 1:
        identities = ", ".join(sorted(spell(c["source"]) for c in usable))
        raise CandidateError(
            f"{name}: {len(usable)} call plans; select one by identity ({identities})"
        )
    plan = usable[0]
    declaration = _declaration(plan, found)
    _check_declared(plan, declaration)
    return plan, declaration


def _declaration(plan: dict[str, Any], found: Inventory) -> Declaration:
    """Find the one pinned declaration a plan records, or refuse."""
    matches = [
        declaration
        for declaration in found.declarations
        if identity(declaration) == plan["source"]
    ]
    if len(matches) != 1:
        raise CandidateError(
            f"{plan['name']}: plan source is not pinned: {spell(plan['source'])}"
        )
    declaration = matches[0]
    if declaration.disposition not in {"ui", "support"}:
        raise CandidateError(
            f"{plan['name']}: source disposition is {declaration.disposition!r}"
        )
    if declaration.name != plan["name"]:
        raise CandidateError(f"{plan['name']}: source names {declaration.name!r}")
    return declaration


def _check_declared(plan: dict[str, Any], declaration: Declaration) -> None:
    """Refuse a plan whose recorded parameters disagree with the declaration."""
    declared = {parameter.name: parameter for parameter in declaration.parameters}
    planned = plan["parameters"]
    if set(declared) != set(planned):
        difference = sorted(set(declared) ^ set(planned))
        raise CandidateError(
            f"{plan['name']}: plan and pin disagree on parameters: {difference}"
        )
    for parameter, spec in planned.items():
        pinned = declared[parameter]
        if pinned.required != spec["required"]:
            raise CandidateError(
                f"{plan['name']}.{parameter}: plan and pin disagree on requiredness"
            )
        if spec["policy"] in {"scalar", "value", "event", "slot"} and (
            pinned.has_default != ("default" in spec)
        ):
            raise CandidateError(
                f"{plan['name']}.{parameter}: plan and pin disagree on defaults"
            )


def derive(
    plan: dict[str, Any],
    declaration: Declaration,
    registry: dict[str, Any],
    decision: dict[str, Any],
) -> Derived:
    """Derive one candidate entry from one selected call plan.

    Args:
        plan: A fresh call plan for exactly one pinned overload.
        declaration: The pinned declaration the plan records.
        registry: The approved catalog, for value families and scopes.
        decision: Review input: ``category``, ``stability`` and optional
            ``since``, none of which the pin decides.

    Returns:
        The candidate entry plus the differences a reviewer must read.

    Raises:
        CandidateError: The decision is incomplete or the plan cannot be
            carried by the wire.
    """
    name = plan["name"]
    for key in ("category", "stability"):
        if not isinstance(decision.get(key), str) or not decision[key]:
            raise CandidateError(f"{name}: the decision needs a non-empty {key!r}")
    props, children, slots, review = wire_shape(name, plan, family_index(registry))
    entry: dict[str, Any] = {
        "package": declaration.package,
        "category": decision["category"],
        "stability": decision["stability"],
    }
    if decision.get("since"):
        entry["since"] = decision["since"]
    entry["source"] = dict(sorted(plan["source"].items()))
    if plan.get("optIn"):
        entry["optIn"] = sorted(plan["optIn"])
    entry["props"] = props
    entry["children"] = children
    if slots:
        entry["slots"] = slots
    return Derived(name, entry, tuple(review))


def stage(registry: dict[str, Any], derived: list[Derived]) -> dict[str, Any]:
    """Insert derived entries into an isolated deep copy of the catalog.

    Args:
        registry: The approved catalog; never modified.
        derived: The derived candidates to stage.

    Returns:
        A candidate registry with every unrelated policy preserved.

    Raises:
        CandidateError: A candidate name is already approved.
    """
    candidate = copy.deepcopy(registry)
    for item in derived:
        if item.name in candidate["components"]:
            raise CandidateError(f"{item.name}: already approved")
        candidate["components"][item.name] = item.entry
    return candidate


def verify(
    candidate: dict[str, Any], found: Inventory, derived: list[Derived]
) -> list[str]:
    """Check a staged candidate against the pin through the production paths.

    Args:
        candidate: The staged candidate registry.
        found: The validated inventory of the current pin.
        derived: The candidates that must resolve as new derived bindings.

    Returns:
        One message per fact the pin or the emitters refuse.
    """
    from tools.schema.check_upstream import compare

    errors = compare(candidate, found)
    fresh = {item.name for item in derived}
    for result in resolutions(candidate, found):
        if result.name in fresh and result.mode != "derived":
            errors.append(f"{result.name}: candidate resolved as {result.mode}")
    try:
        _framework_artifacts(candidate)
    except (SystemExit, ValueError) as exc:
        errors.append(f"generation refused the candidate: {exc}")
    return errors


def _framework_artifacts(candidate: dict[str, Any]) -> dict[Path, str]:
    """Render every production artifact from a candidate, writing nothing."""
    from pycompose.schema.codegen.main import framework_artifacts

    return framework_artifacts(candidate)


def review_manifest(plans: dict[str, Any], derived: list[Derived]) -> dict[str, Any]:
    """Build the review manifest staged next to the candidate registry.

    Args:
        plans: The planner document the candidates came from.
        derived: The derived candidates.

    Returns:
        A deterministic manifest of identity and differences per candidate.
    """
    return {
        "formatVersion": 1,
        "bom": plans["bom"],
        "compiler": plans["compiler"],
        "candidates": {
            item.name: {
                "source": item.entry["source"],
                "review": list(item.review),
            }
            for item in sorted(derived, key=lambda item: item.name)
        },
    }


def _derive_all(
    plans: dict[str, Any],
    found: Inventory,
    registry: dict[str, Any],
    decisions: dict[str, Any],
    names: list[str],
) -> list[Derived]:
    """Derive one candidate per requested name, refusing duplicates."""
    derived = []
    for name in names:
        if name in registry["components"]:
            raise CandidateError(f"{name}: already approved")
        decision = decisions.get(name)
        if decision is None:
            raise CandidateError(f"{name}: no decision")
        plan, declaration = select(plans, found, name)
        derived.append(derive(plan, declaration, registry, decision))
    return derived


def _write(
    args: argparse.Namespace,
    plans: dict[str, Any],
    derived: list[Derived],
    candidate: dict[str, Any],
) -> None:
    """Write the staged registry and review manifest, never the catalog."""
    if args.out is not None:
        if args.out.resolve() == args.schema.resolve():
            raise CandidateError(
                "--out is the approved schema; candidates are staged, never "
                "approved by tooling"
            )
        args.out.write_text(dumps(candidate), encoding="utf-8")
    if args.review is not None:
        args.review.write_text(dumps(review_manifest(plans, derived)), encoding="utf-8")


def _print_review(derived: list[Derived]) -> None:
    """Print the compatibility differences of every derived candidate."""
    for item in derived:
        print(f"--- {item.name}")
        for note in item.review:
            print(f"  - {note}")


def main(argv: list[str] | None = None) -> int:
    """Derive, verify and stage candidates; never approve them.

    Args:
        argv: Command-line arguments, defaulting to ``sys.argv[1:]``.

    Returns:
        Process exit status: 0 staged, 1 verification refusal, 2 input error.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("names", nargs="+")
    parser.add_argument(
        "--plans",
        type=Path,
        default=Path("android/build/compose-api/components.json"),
    )
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--directory", type=Path, default=DUMP_DIR)
    parser.add_argument("--schema", type=Path, default=Path("schema/components.json"))
    parser.add_argument("--out", type=Path)
    parser.add_argument("--review", type=Path)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    try:
        plans = json.loads(args.plans.read_text(encoding="utf-8"))
        registry = json.loads(args.schema.read_text(encoding="utf-8"))
        decisions = json.loads(args.decisions.read_text(encoding="utf-8"))
        found = inventory(args.directory)
        check_fresh(plans, found)
        derived = _derive_all(plans, found, registry, decisions, args.names)
        candidate = stage(registry, derived)
        errors = verify(candidate, found, derived)
        if errors:
            for error in errors:
                print(error, file=sys.stderr)
            return 1
        _write(args, plans, derived, candidate)
        for item in derived:
            print(f"{item.name}: candidate entry, {len(item.review)} difference(s)")
        if args.summary:
            _print_review(derived)
        return 0
    except (OSError, ValueError) as exc:
        print(f"entry_candidates.py: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover - only when run as a script
    raise SystemExit(main())
