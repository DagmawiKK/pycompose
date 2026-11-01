"""What the account can bind: the approved value props, and the converter each lacks.

The census is the binding backlog. Every prop that carries a value lands in one
bucket, so no prop is silently unbindable: the host can animate it (the pin
declares a converter for its type and Python is the value's sole author), a
state holder owns it (the user's, and a later protocol's), or the converter it
needs is named here. The account classifies those reasons and refuses one its
table cannot name.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from pycompose_codegen.derive.converters import kotlin_type
from pycompose_codegen.emit.adapters.eligibility import held_props

VALUE_TYPES = frozenset(
    {
        "boolean",
        "color",
        "dp",
        "durationMs",
        "enum",
        "integer",
        "number",
        "resource",
        "string",
        "value",
    }
)
"""The prop types that carry a value a binding could target.

An action is not a value and a modifier is a list of operations, so neither is
counted here: the census is about the props the host could animate.
"""


def _no_converter(kotlin: str | None) -> str:
    """Why a prop cannot be bound, naming the type whose converter is missing.

    Args:
        kotlin: The Kotlin type the lock states for the prop, when it states one.

    Returns:
        The reason, whose class is ``binding-protocol`` either way.
    """
    if kotlin is None:
        return "no animation converter: the lock states no Kotlin type"
    return f"no animation converter for {kotlin}"


def binding_states(
    registry: dict[str, Any],
) -> tuple[Counter[str], Counter[str]]:
    """Count the approved value props by binding state, and why the rest cannot.

    A binding needs two things, and each prop lands in exactly one bucket: the
    pin declares a converter for the prop's type (capability), and Python is the
    value's sole author (authority). A prop a state holder fills is the user's,
    so it waits for a protocol of its own; every other unbindable prop names the
    converter it lacks, and the account refuses a reason it cannot classify.

    Args:
        registry: The approved catalog.

    Returns:
        The states (``bindable``, ``held``) and the reason each unbindable prop
        gives, both counted.
    """
    families = registry.get("valueTypes", {})
    states: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    for section in ("components", "modifiers"):
        for entry in registry.get(section, {}).values():
            held = held_props(entry)
            for prop, spec in entry.get("props", {}).items():
                if spec.get("type") not in VALUE_TYPES:
                    continue
                if prop in held:
                    states["held"] += 1
                elif "animation" in spec:
                    states["bindable"] += 1
                else:
                    kotlin = kotlin_type(prop, spec, entry, families)
                    reasons[_no_converter(kotlin)] += 1
    return states, reasons
