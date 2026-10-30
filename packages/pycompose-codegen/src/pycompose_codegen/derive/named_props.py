"""Props whose value an app names: a constant family's members, by Compose's name."""

from __future__ import annotations

from typing import Any


def named(family: dict[str, Any]) -> bool:
    """Whether an app names this family's values by string (``centerHorizontally``).

    A family made only of constants whose names are identifiers is; one also
    built by a constructor, or named by paths (icons), is a value an app builds.
    """
    if family.get("kind") != "constant":
        return False
    names = (family.get("parameters") or {}).get("name", {}).get("values") or []
    return bool(names) and all(str(name).isidentifier() for name in names)


def enum_prop(
    name: str,
    parameter: str,
    spec: dict[str, Any],
    family: dict[str, Any],
    review: list[str],
) -> dict[str, Any] | None:
    """Derive a constant family an app names by string.

    The app writes a constant's name camelCased; the wire carries the family's
    tagged constant, and an absent prop takes the native default it names.
    """
    # The candidate module builds every prop kind and dispatches here.
    from pycompose_codegen.derive.candidate_props import (
        CandidateError,
        _camel,
        _render,
    )

    values = (family.get("parameters") or {}).get("name", {}).get("values")
    if not values:
        raise CandidateError(
            f"{name}.{parameter}: family {spec['family']!r} has no value names"
        )
    prop: dict[str, Any] = {
        "type": "enum",
        "valueType": spec["family"],
        "values": [_camel(value) for value in values],
    }
    if spec["required"]:
        prop["required"] = True
        review.append(f"{parameter}: named {spec['family']} constant")
        return prop
    symbol = (spec.get("default") or {}).get("symbol")
    last = str(symbol).rsplit(".", 1)[-1] if symbol else ""
    if last not in values:
        # Not one of its names (null, say): absent takes the rendered default.
        _, rendered = _render(parameter, spec, review)
        if rendered is None:
            review.append(
                f"{parameter}: omitted; default {symbol!r} is not a named constant"
            )
            return None
        # Absent takes the default, null included; an app never sends null.
        prop["nativeDefault"] = rendered
        review.append(
            f"{parameter}: named {spec['family']} constant, absent {rendered}"
        )
        return prop
    prop["default"] = _camel(last)
    prop["nativeDefault"] = symbol
    review.append(f"{parameter}: named {spec['family']} constant, default {last}")
    return prop
