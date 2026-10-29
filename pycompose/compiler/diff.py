"""Classify every difference between two catalog locks (plan 31 §9).

An upgrade or a policy change regenerates the lock; this says what that means
for an app. Each change gets a stable id and one class:

- ``additive``: something new an existing app does not have to use.
- ``fidelity``: the same API renders differently (a default, a token, a pin).
- ``metadata``: bookkeeping no app observes (``since``, ``reshaped``, category).
- ``behaviour``: the same call behaves differently (state, payloads, stability).
- ``breaking``: an existing call stops being valid.

The first three are accepted automatically. Behaviour and breaking changes
need an approval in ``schema/policy/approvals.json``, keyed by change id, and
an approval that names no current change fails the run, so the file only ever
holds decisions about the change under review.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pycompose.codegen.checkout import ROOT

APPROVALS = ROOT / "schema/policy/approvals.json"
AUTOMATIC = frozenset({"additive", "fidelity", "metadata"})
METADATA = frozenset({"since", "reshaped", "category", "package"})
FIDELITY = frozenset({"default", "nativeDefault", "fallback"})


@dataclass(frozen=True)
class Change:
    """One classified difference.

    Attributes:
        id: Stable identity: the lock path and what happened to it.
        kind: The class; see the module docstring.
    """

    id: str
    kind: str


def classify(old: dict[str, Any], new: dict[str, Any]) -> list[Change]:
    """Classify every difference between two locks.

    Args:
        old: The base lock.
        new: The lock under review.

    Returns:
        The changes, sorted by id.
    """
    changes: list[Change] = []
    for section in sorted(old.keys() | new.keys()):
        before, after = old.get(section), new.get(section)
        if before == after:
            continue
        if section == "components":
            changes += _keyed(section, before or {}, after or {}, _component)
        elif section == "valueTypes":
            changes += _keyed(section, before or {}, after or {}, _value)
        elif isinstance(before, dict) and isinstance(after, dict):
            changes += _keyed(section, before, after, _changed)
        else:
            changes.append(Change(f"{section}:changed", "metadata"))
    return sorted(changes, key=lambda change: change.id)


def _keyed(
    path: str,
    old: dict[str, Any],
    new: dict[str, Any],
    changed: Callable[[str, Any, Any], list[Change]],
) -> list[Change]:
    """Added entries are additive, removed ones breaking; the rest by ``changed``."""
    changes = []
    for key in sorted(old.keys() | new.keys()):
        where = f"{path}.{key}"
        if key not in old:
            changes.append(Change(f"{where}:added", "additive"))
        elif key not in new:
            changes.append(Change(f"{where}:removed", "breaking"))
        elif old[key] != new[key]:
            changes += changed(where, old[key], new[key])
    return changes


def _changed(where: str, *_: Any) -> list[Change]:
    """A change no finer rule classifies: conservatively, behaviour."""
    return [Change(f"{where}:changed", "behaviour")]


def _value(where: str, old: Any, new: Any) -> list[Change]:
    """A value binding re-pinned to a newer artifact is fidelity, like a component."""
    if (
        isinstance(old, dict)
        and isinstance(new, dict)
        and {k: v for k, v in old.items() if k != "source"}
        == {k: v for k, v in new.items() if k != "source"}
    ):
        return [
            Change(
                f"{where}.source:changed", _source(old.get("source"), new.get("source"))
            )
        ]
    return _changed(where)


def _component(where: str, old: dict[str, Any], new: dict[str, Any]) -> list[Change]:
    changes = []
    for key in sorted(old.keys() | new.keys()):
        before, after = old.get(key), new.get(key)
        if before == after:
            continue
        path = f"{where}.{key}"
        if key == "props":
            changes += _props(path, before or {}, after or {})
        elif key == "slots":
            changes += _slots(path, before or {}, after or {})
        elif key in METADATA:
            changes.append(Change(f"{path}:changed", "metadata"))
        elif key == "source":
            changes.append(Change(f"{path}:changed", _source(before, after)))
        elif key == "children":
            changes.append(Change(f"{path}:changed", _children(before, after)))
        elif key == "interaction" and before is None:
            # Observation added: optional report props, nothing an app must pass.
            changes.append(Change(f"{path}:added", "additive"))
        else:
            changes += _changed(path, before, after)
    return changes


def _props(where: str, old: dict[str, Any], new: dict[str, Any]) -> list[Change]:
    changes = []
    for name in sorted(old.keys() | new.keys()):
        path = f"{where}.{name}"
        if name not in old:
            kind = "breaking" if new[name].get("required") else "additive"
            changes.append(Change(f"{path}:added", kind))
        elif name not in new:
            changes.append(Change(f"{path}:removed", "breaking"))
        elif old[name] != new[name]:
            changes += _prop(path, old[name], new[name])
    return changes


def _prop(where: str, old: dict[str, Any], new: dict[str, Any]) -> list[Change]:
    changes = []
    for key in sorted(old.keys() | new.keys()):
        before, after = old.get(key), new.get(key)
        if before == after:
            continue
        if key == "type":
            kind = "breaking"
        elif key == "required":
            kind = "breaking" if after else "additive"
        elif key == "values":
            kind = "breaking" if set(before or ()) - set(after or ()) else "additive"
        elif key == "minimum":
            kind = (
                "breaking"
                if after is not None and (before is None or after > before)
                else "additive"
            )
        elif key == "maximum":
            kind = (
                "breaking"
                if after is not None and (before is None or after < before)
                else "additive"
            )
        elif key in FIDELITY:
            kind = "fidelity"
        elif key in METADATA:
            kind = "metadata"
        else:
            kind = "behaviour"
        changes.append(Change(f"{where}.{key}:changed", kind))
    return changes


def _slots(where: str, old: dict[str, Any], new: dict[str, Any]) -> list[Change]:
    changes = []
    for name in sorted(old.keys() | new.keys()):
        path = f"{where}.{name}"
        if name not in old:
            optional = new[name].get("nullable") or new[name].get("host")
            changes.append(
                Change(f"{path}:added", "additive" if optional else "breaking")
            )
        elif name not in new:
            changes.append(Change(f"{path}:removed", "breaking"))
        elif old[name] != new[name]:
            changes.append(Change(f"{path}:changed", "behaviour"))
    return changes


def _source(old: dict[str, Any] | None, new: dict[str, Any] | None) -> str:
    """The same overload in a newer artifact is fidelity; another overload is not."""
    same = old and new and {**old, "artifact": None} == {**new, "artifact": None}
    return "fidelity" if same else "behaviour"


def _children(old: dict[str, Any] | None, new: dict[str, Any] | None) -> str:
    allowed = (old or {}).get("allowed"), (new or {}).get("allowed")
    if allowed == (True, False):
        return "breaking"
    return "additive" if allowed == (False, True) else "behaviour"


def unapproved(
    changes: list[Change], approvals: dict[str, str]
) -> tuple[list[Change], list[str]]:
    """Find the changes that need an approval they lack, and stale approvals.

    Args:
        changes: The classified changes.
        approvals: Change id to the reason it was accepted.

    Returns:
        Changes needing approval, and approvals naming no current change.
    """
    ids = {change.id for change in changes}
    missing = [c for c in changes if c.kind not in AUTOMATIC and c.id not in approvals]
    stale = sorted(set(approvals) - ids)
    return missing, stale


def load_approvals(path: Path = APPROVALS) -> dict[str, str]:
    """Read the approvals file; no file means nothing is approved.

    Args:
        path: The approvals file.

    Returns:
        Change id to reason.
    """
    if not path.is_file():
        return {}
    approved: dict[str, str] = json.loads(path.read_text(encoding="utf-8"))["approved"]
    return approved
