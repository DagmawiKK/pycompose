"""Expose every overload of a catalog component behind its name (plan 31 §12.5).

The catalog binds one overload per decision; the pin often has more -- a plain
``Card`` beside the clickable one, a determinate progress indicator beside the
indeterminate one. Each extra overload derives like any component, with its
primary's review decisions, and takes a name of its own on the wire. When
keywords tell it from its siblings it joins the primary's Python name
(``overloadOf``); when they cannot, its name is the callable.

The name is derived: the first required parameter the primary lacks, else the
type that differs, else ``Without`` the primary's first required parameter it
drops. An overload is skipped, with the reason reported, when it does not
derive, needs a hand-written adapter, binds a state holder its primary does
not, adds no call the primary lacks, or cannot be told from the primary by
name at all.
"""

from __future__ import annotations

from typing import Any

from pycompose_codegen.derive.candidate_props import CandidateError
from pycompose_codegen.derive.component_binding import spell
from pycompose_codegen.emit.adapters.eligibility import is_mechanical
from pycompose_codegen.emit.adapters.policy import pascal
from pycompose_codegen.emit.overloads import ambiguous, keywords


def _required(plan: dict[str, Any]) -> dict[str, str]:
    """Required parameters, in declaration order, with their classifiers."""
    return {
        name: spec["type"]["classifier"]
        for name, spec in plan["parameters"].items()
        if spec["required"] and spec["policy"] != "modifier"
    }


def suffix(plan: dict[str, Any], primary: dict[str, Any]) -> str | None:
    """Derive an overload's name suffix from what sets it apart.

    Args:
        plan: The overload's call plan.
        primary: The primary's call plan.

    Returns:
        The suffix, or None when no required parameter differs.
    """
    own, theirs = _required(plan), _required(primary)
    everything = {
        name: spec["type"]["classifier"] for name, spec in primary["parameters"].items()
    }
    for name, classifier in own.items():
        if theirs.get(name) == classifier:
            continue
        if name not in everything:
            return pascal(name)
        return classifier.rsplit("/", 1)[-1]
    dropped = [name for name in theirs if name not in plan["parameters"]]
    return f"Without{pascal(dropped[0])}" if dropped else None


def extras(
    components: dict[str, Any],
    decisions: dict[str, dict[str, Any]],
    plans: dict[str, Any],
    derive: Any,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Derive every overload the catalog's primaries do not bind yet.

    Args:
        components: The lock's components so far.
        decisions: Each derived component's policy decision.
        plans: The planner's call plans for the pin.
        derive: Derives one entry: ``derive(name, decision)``.

    Returns:
        The new entries by name, and each skipped overload's reason.
    """
    bound = {
        spell(entry["source"]) for entry in components.values() if "source" in entry
    }
    by_source = {spell(plan["source"]): plan for plan in plans["candidates"]}
    added: dict[str, Any] = {}
    skipped: dict[str, str] = {}
    for name, decision in sorted(decisions.items()):
        entry = components[name]
        if "source" not in entry:
            # A hand-written adapter spanning a family binds no one overload.
            continue
        primary = by_source.get(spell(entry["source"]))
        if primary is None or entry["source"]["name"] != name:
            continue
        for plan in _siblings(plans, primary, bound):
            label = f"{name} {plan['source']['jvmName']}"
            tail = suffix(plan, primary)
            if tail is None:
                skipped[label] = "no required parameter tells it from the primary"
                continue
            extra = name + tail
            outcome = _derive(extra, name, decision, plan, components, added, derive)
            if isinstance(outcome, str):
                skipped[label] = outcome
            else:
                added[extra] = outcome
    return added, skipped


def _siblings(
    plans: dict[str, Any], primary: dict[str, Any], bound: set[str]
) -> list[dict[str, Any]]:
    """The primary's other usable, current overloads no component binds."""
    return [
        plan
        for plan in plans["candidates"]
        if plan["name"] == primary["name"]
        and plan["surface"] == "component"
        and plan["status"] == "call-plan"
        and "kotlin/Deprecated" not in (plan.get("annotations") or {})
        and spell(plan["source"]) not in bound
    ]


def _derive(
    extra: str,
    name: str,
    decision: dict[str, Any],
    plan: dict[str, Any],
    components: dict[str, Any],
    added: dict[str, Any],
    derive: Any,
) -> dict[str, Any] | str:
    """One overload's entry, or the reason it is not exposed."""
    if extra in components or extra in added:
        return f"its derived name {extra!r} is taken"
    parameters = plan["parameters"]
    own = {
        "category": decision["category"],
        "stability": decision["stability"],
        "nativeName": name,
        "identity": spell(plan["source"]),
    }
    if decision.get("observe") is False:
        own["observe"] = False
    flatten = [slot for slot in decision.get("flatten", ()) if slot in parameters]
    if flatten:
        own["flatten"] = flatten
    try:
        entry: dict[str, Any] = derive(extra, own)
    except CandidateError as exc:
        return str(exc).split(": ", 1)[-1]
    if not is_mechanical(entry):
        return "needs a hand-written adapter"
    if "state" in entry and "state" not in components[name]:
        # A drawer sheet's DrawerState is its drawer's, not one of its own:
        # which holder an overload shares is a decision, not a keyword.
        return "binds a state holder its primary does not"
    if entry.get("optIn"):
        entry["stability"] = "experimental"
    required, accepted = keywords(entry)
    primary_required, primary_accepted = keywords(components[name])
    if accepted <= primary_accepted and primary_required <= required:
        return f"every call is already a call to {name}"
    group = [
        components[name],
        *(e for e in added.values() if e.get("overloadOf") == name),
    ]
    if not any(ambiguous(entry, member) for member in group):
        entry["overloadOf"] = name
    return entry
