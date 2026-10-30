"""The policy overlay: the only hand-authored input to the component compiler.

Evidence answers what the pin says; policy records what a person decided. For a
component the pin can describe, policy holds the review decisions the pin
cannot make (category, stability, which overload) and a merge patch over the
derived entry for whatever a person shaped differently. A component the pin
cannot yet describe is held whole, with the reason, until a mechanism lands.
Everything else in the catalog that no derivation produces yet -- values,
actions, effects, lifecycle, modifiers, versions -- is held as sections.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pycompose_codegen.checkout import ROOT

POLICY = ROOT / "schema/policy"


@dataclass(frozen=True)
class Policy:
    """What people decided, by concern.

    Attributes:
        sections: Catalog sections no derivation produces yet.
        components: Per component: ``decision`` and an optional ``patch``,
            ``manual`` (the reason it is held whole) and ``entry``, or
            ``refuse`` (why a component that derives is not exposed).
    """

    sections: dict[str, Any]
    components: dict[str, dict[str, Any]]


def load(directory: Path = POLICY) -> Policy:
    """Read the policy overlay.

    Args:
        directory: The policy directory.

    Returns:
        The policy.
    """
    return Policy(
        sections=json.loads((directory / "catalog.json").read_text(encoding="utf-8")),
        components=json.loads(
            (directory / "components.json").read_text(encoding="utf-8")
        ),
    )


def merge(base: Any, patch: Any) -> Any:
    """Apply a JSON merge patch (RFC 7386): objects merge, null deletes.

    Args:
        base: The derived value.
        patch: What a person changed about it.

    Returns:
        The patched value; ``base`` is not modified.
    """
    if not isinstance(patch, dict):
        return patch
    merged = dict(base) if isinstance(base, dict) else {}
    for key, value in patch.items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = merge(merged.get(key), value)
    return merged


def diff(base: Any, target: Any) -> Any:
    """Return the smallest merge patch turning ``base`` into ``target``.

    Args:
        base: The derived value.
        target: The value a person approved.

    Returns:
        The patch; an empty object when they are equal.
    """
    if not isinstance(base, dict) or not isinstance(target, dict):
        return target
    patch: dict[str, Any] = {key: None for key in base if key not in target}
    for key, value in target.items():
        if key not in base:
            patch[key] = value
        elif base[key] != value:
            patch[key] = diff(base[key], value)
    return patch


def redundant(base: Any, patch: Any, path: str = "") -> list[str]:
    """List the parts of a patch the derivation already produces.

    A patch entry equal to what the pin now implies is a decision nobody needs
    to keep making; reporting it keeps the overlay as small as the evidence
    allows.

    Args:
        base: The derived value.
        patch: The policy's patch over it.
        path: Where this value sits, for the report.

    Returns:
        The dotted paths of patch entries that change nothing.
    """
    if not isinstance(patch, dict) or not isinstance(base, dict):
        return [path] if patch == base else []
    found: list[str] = []
    for key, value in patch.items():
        where = f"{path}.{key}" if path else key
        if value is None:
            if key not in base:
                found.append(where)
        elif key in base:
            found.extend(redundant(base[key], value, where))
    return found


def removals(
    name: str, patch: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, str], list[str]]:
    """Apply each prop removal in a patch, keeping every removal's reason.

    A prop leaves a derived entry only as ``{"refuse": "why"}``, which the report
    prints; a bare null would remove it with no reason anyone can read.

    Args:
        name: The component.
        patch: Its policy patch.

    Returns:
        The patch with each refused prop as a deletion, the reasons by
        ``Component.prop``, and an error for each removal that gives none.
    """
    props = patch.get("props")
    if not isinstance(props, dict):
        return patch, {}, []
    applied: dict[str, Any] = {}
    reasons: dict[str, str] = {}
    errors: list[str] = []
    for prop, change in props.items():
        if change is None:
            errors.append(
                f'{name}.{prop}: removed without a reason; write {{"refuse": "why"}}'
            )
        refused = isinstance(change, dict) and set(change) == {"refuse"}
        if refused:
            reasons[f"{name}.{prop}"] = change["refuse"]
        applied[prop] = None if refused else change
    return {**patch, "props": applied}, reasons, errors


def unclaimed(entry: dict[str, Any]) -> dict[str, Any]:
    """The entry without props for parameters something else already fills.

    A holder that wires a sheet's dismissal, or an interaction source the host
    remembers, owns that parameter; offering it as a prop too would bind it
    twice.

    Args:
        entry: A component entry, policy applied.

    Returns:
        The entry, its claimed props removed.
    """
    state = entry.get("state") or {}
    sources = (
        state.get("native"),
        state.get("dismiss"),
        (entry.get("transient") or {}).get("native"),
        (entry.get("interaction") or {}).get("native"),
    )
    claimed = {source for source in sources if isinstance(source, str)}
    props = entry.get("props", {})
    if not claimed.intersection(props):
        return entry
    return {
        **entry,
        "props": {name: spec for name, spec in props.items() if name not in claimed},
    }


def stability(entry: dict[str, Any]) -> dict[str, Any]:
    """The entry with the stability its opt-ins state, once policy applied.

    A component whose call needs an opt-in marker is experimental; read after
    the patch, so one whose marker policy removed is stable again.

    Args:
        entry: A component entry, policy applied.

    Returns:
        The entry, its ``stability`` set.
    """
    return {**entry, "stability": "experimental" if entry.get("optIn") else "stable"}
