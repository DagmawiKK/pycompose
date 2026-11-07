"""What the planner reports beside its plans: coverage and a capability worklist."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any


def worklist(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group recorded gaps by the capability that would close them.

    Each reason lists the components it blocks, the hooks it blocks (styling
    hooks are parameter support, so their gaps never read as component
    blockers), and the names it only limits — so capabilities can be added in
    one deliberate batch instead of overload by overload.
    """
    blocking: dict[str, set[str]] = defaultdict(set)
    hooks: dict[str, set[str]] = defaultdict(set)
    limiting: dict[str, set[str]] = defaultdict(set)
    for candidate in candidates:
        for gap in candidate["gaps"]:
            if not gap["required"]:
                limiting[gap["reason"]].add(candidate["name"])
            elif candidate["surface"] == "hook":
                hooks[gap["reason"]].add(candidate["name"])
            else:
                blocking[gap["reason"]].add(candidate["name"])
    return [
        {
            "reason": reason,
            "blocks": sorted(blocking[reason]),
            "hooks": sorted(hooks[reason]),
            "limits": sorted(limiting[reason]),
        }
        for reason in sorted(blocking.keys() | hooks.keys() | limiting.keys())
    ]


def surface_coverage(candidates: list[dict[str, Any]], surface: str) -> dict[str, int]:
    """Count what one surface offers, keeping hooks out of the component tally."""
    subset = [c for c in candidates if c["surface"] == surface]
    statuses = Counter(c["status"] for c in subset)
    return {
        "names": len({c["name"] for c in subset}),
        "overloads": len(subset),
        "callPlan": statuses["call-plan"],
        "blocked": statuses["blocked"],
    }
