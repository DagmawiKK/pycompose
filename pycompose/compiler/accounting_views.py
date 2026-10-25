"""What the account compiles against: the catalog, the pin and the call plans.

The account's questions are all relational -- is this declaration already
consumed by an approved binding, does an approved component still have a call
plan, does a target diagnostic remain. This module projects the approved
catalog, the pinned inventory and the planner's candidates into the sets and
views those questions need; :mod:`pycompose.compiler.accounting` turns them into the
report. Nothing here writes, approves or edits anything.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from pycompose.compiler.classpath_dump import Declaration, Inventory
from pycompose.core.registry_vocabulary import (
    STATE_KINDS,
    TRANSIENT_KINDS,
)


def normalize(path: str) -> str:
    """Return one dotted form for a classifier or owner path.

    Args:
        path: A slash- or dot-separated classifier path, possibly carrying
            ``$`` for a nested class.

    Returns:
        The dotted form with nested classes joined by dots.
    """
    return path.replace("/", ".").replace("$", ".")


def empty_bucket() -> dict[str, Any]:
    """Return one domain's accumulator with a bucket for every accounting view."""
    return {
        "declarations": Counter(),
        "components": {"approved": set(), "planned": set(), "blocked": set()},
        "hooks": {"planned": set(), "blocked": set()},
        "support": Counter(),
        "gaps": Counter(),
        "overloads": Counter(),
    }


def placement(candidate: dict[str, Any], approved_calls: set[str]) -> tuple[str, str]:
    """Report the surface and the one accounting bucket a candidate lands in.

    Args:
        candidate: One planned overload from the component planner.
        approved_calls: Dotted calls of the approved catalog's components.

    Returns:
        The surface (``components`` or ``hooks``) and the bucket
        (``approved``, ``planned`` or ``blocked``).
    """
    surface = "components" if candidate["surface"] == "component" else "hooks"
    if candidate["status"] != "call-plan":
        return surface, "blocked"
    if surface == "components" and candidate["call"] in approved_calls:
        return surface, "approved"
    return surface, "planned"


def receivers(declaration: Declaration) -> list[str]:
    """Return every receiver classifier a declaration carries, slash form."""
    classifiers = [
        value.classifier
        for value in (declaration.receiver, declaration.dispatch_receiver)
        if value is not None
    ]
    classifiers.extend(value.classifier for value in declaration.context_receivers)
    return classifiers


def approval_facts(
    registry: dict[str, Any], candidates: list[dict[str, Any]]
) -> dict[str, Any]:
    """Collect what the approved catalog and the planned call plans consume.

    Args:
        registry: The approved catalog.
        candidates: The planner's call plans.

    Returns:
        Identity, holder, scope and planned-owner sets used for recognition.
    """
    identities: set[tuple[str, str]] = set()
    jvm_identities: set[tuple[str, str, str]] = set()
    holders: set[str] = set()
    for spec in registry["valueTypes"].values():
        source = spec.get("source", {})
        owner = normalize(source["owner"]) if source.get("owner") else None
        if owner is not None:
            holders.add(owner)
            if source.get("name"):
                identities.add((owner, source["name"]))
            if source.get("jvmName") and source.get("descriptor"):
                jvm_identities.add((owner, source["jvmName"], source["descriptor"]))
        native = spec.get("native", {})
        holders.update(
            normalize(expression)
            for expression in (
                native.get("propertyOwner"),
                *native.get("owners", {}).values(),
            )
            if expression
        )
    planned_owners: set[str] = set()
    for candidate in candidates:
        if candidate["status"] != "call-plan":
            continue
        planned_owners.update(
            normalize(parameter["type"]["classifier"])
            for parameter in candidate["parameters"].values()
        )
        if candidate["receiver"]:
            planned_owners.add(normalize(candidate["receiver"]["classifier"]))
    return {
        "identities": identities,
        "jvmIdentities": jvm_identities,
        "holders": holders,
        "plannedOwners": planned_owners,
        # The receivers planned slots hand down: what a scope member composes in.
        "scopes": frozenset(
            parameter["receiver"]
            for candidate in candidates
            for parameter in candidate["parameters"].values()
            if parameter.get("policy") == "slot" and parameter.get("receiver")
        ),
    }


def recognition(declaration: Declaration, facts: dict[str, Any]) -> str:
    """Report what already consumes one support declaration."""
    owner = normalize(declaration.owner)
    if (owner, declaration.name) in facts["identities"]:
        return "approved"
    if (
        declaration.jvm_name
        and declaration.jvm_descriptor
        and (owner, declaration.jvm_name, declaration.jvm_descriptor)
        in facts["jvmIdentities"]
    ):
        return "approved"
    if any(classifier in facts["scopes"] for classifier in receivers(declaration)):
        return "scope-member"
    if any(
        owner == holder or owner.startswith(holder + ".") for holder in facts["holders"]
    ):
        return "holder-member"
    if owner in facts["plannedOwners"]:
        return "planned"
    return "unrecognized"


def protocols(registry: dict[str, Any]) -> dict[str, Any]:
    """Report the host protocols the approved catalog activates, and their coverage."""
    components = registry["components"]
    view: dict[str, Any] = {
        "actions": sorted(registry["actions"]),
        "effects": sorted(registry["effects"]),
        "lifecycle": sorted(registry["lifecycle"]),
        "modifiers": sorted(registry["modifiers"]),
    }
    for key in ("state", "transient", "interaction", "adapter", "wrapper"):
        view[key] = sorted(name for name, spec in components.items() if key in spec)
    view["stateByKind"] = {
        kind: sorted(
            name
            for name, spec in components.items()
            if spec.get("state", {}).get("kind") == kind
        )
        for kind in STATE_KINDS
    }
    view["transientByKind"] = {
        kind: sorted(
            name
            for name, spec in components.items()
            if spec.get("transient", {}).get("kind") == kind
        )
        for kind in TRANSIENT_KINDS
    }
    view["scopes"] = sorted(
        name for name, spec in components.items() if spec.get("scope")
    )
    view["slots"] = sorted(name for name, spec in components.items() if "slots" in spec)
    view["reshaped"] = sorted(
        name for name, spec in components.items() if "reshaped" in spec
    )
    return view


def grounding(
    registry: dict[str, Any], plan: dict[str, Any], found: Inventory
) -> dict[str, list[str]]:
    """Reconcile approved components and value sources against the planned pin."""
    calls = {
        candidate["call"]
        for candidate in plan["candidates"]
        if candidate["status"] == "call-plan"
    }
    components = sorted(
        name
        for name, spec in registry["components"].items()
        if spec["package"] + "." + name not in calls
    )
    pinned = {
        (normalize(declaration.owner), declaration.jvm_name, declaration.jvm_descriptor)
        for declaration in found.declarations
    }
    values = sorted(
        name
        for name, spec in registry["valueTypes"].items()
        if (source := spec.get("source", {})).get("jvmName")
        and (
            normalize(source.get("owner") or ""),
            source["jvmName"],
            source.get("descriptor"),
        )
        not in pinned
    )
    return {"ungroundedComponents": components, "ungroundedValues": values}
