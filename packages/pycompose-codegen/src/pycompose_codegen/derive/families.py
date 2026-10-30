"""Value families re-derived from the pin each run, from what policy decided.

Policy names a family's source declaration and the decisions the pin cannot
make: which parameters the wire carries and their bounds, and a family or role
a person chose. Everything else -- each parameter's type and default, the
native call, the opt-ins it needs -- is derived again from the pin, so a pin
update changes the family with no edit to policy.
"""

from __future__ import annotations

from typing import Any

from pycompose_codegen.derive.classpath_dump import Inventory
from pycompose_codegen.derive.propose_families import bind


def bound_families(
    sections: dict[str, Any],
    found: Inventory,
    evidence: dict[tuple[str, str, str], dict[str, Any]],
    stamp: Any,
) -> tuple[dict[str, Any], list[str]]:
    """Derive every sourced family; keep the rest as policy states them.

    A family's parameters may take other families (``buttonColors`` takes
    ``Color``), which a binding finds by their derived types; so families are
    bound in passes, each pass seeing what the last derived, until no more
    bind.

    Args:
        sections: The policy sections, ``valueTypes`` holding decisions.
        found: The pinned inventory.
        evidence: Compiler-resolved defaults by JVM identity.
        stamp: Writes a policy source at the pinned artifact version.

    Returns:
        The sections with derived families, and each family that does not derive.
    """
    values = dict(sections.get("valueTypes", {}))
    pending = {name for name, spec in values.items() if _sourced(spec)}
    reasons: dict[str, str] = {}
    while pending:
        registry = {**sections, "valueTypes": values}
        bound = set()
        for name in sorted(pending):
            result = bind(found, evidence, registry, name)
            if "proposal" in result:
                values[name] = result["proposal"]
                bound.add(name)
            else:
                reasons[name] = str(result.get("unsupported") or result.get("reason"))
        if not bound:
            break
        pending -= bound
    for name in pending:
        values[name] = {**values[name], "source": stamp(values[name]["source"])}
    errors = [f"value {name}: {reasons[name]}" for name in sorted(pending)]
    return {**sections, "valueTypes": values}, errors


def _sourced(spec: Any) -> bool:
    """Whether policy states a family by the declaration the pin binds it from."""
    if not isinstance(spec, dict) or not isinstance(spec.get("source"), dict):
        return False
    return "language" not in spec["source"] and ("family" in spec or _bindable(spec))


def _bindable(spec: dict[str, Any]) -> bool:
    """Whether an entry without a stated ``family`` is still one the pin binds."""
    return "kind" in spec or "parameters" in spec or "source" in spec
