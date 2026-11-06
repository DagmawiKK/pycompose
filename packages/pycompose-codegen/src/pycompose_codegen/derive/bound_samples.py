"""Two frames of one bound prop, for the binding gate.

Every prop the pin gives a converter is rendered twice: first with a target the
catalog derives, then with that target moved, so the host travels between them
rather than merely reading a plain value. The snapshot itself is the ordinary
component sample (:mod:`pycompose_codegen.derive.samples`); this module only
states the bound prop and whatever the target's range needs, so nothing about
components or props is listed here.
"""

from __future__ import annotations

from typing import Any, cast

from pycompose_codegen.derive.samples import _value, sample

COLOURS = (0xFF6750A4, 0xFFB3261E)
"""Two packed colours: the target, then the one the second frame travels to."""

PACKED = frozenset({"int", "integer", "long"})
"""The parameter types that carry a colour's packed value."""

DP = 64
"""The dp a bound prop states when it declares no value of its own, and the pin
states none for its native default either.

A prop with no literal default still has to be a value its component accepts.
The app bars require their expanded height to reach their collapsed one, whose
Material default is this: the bar height. A smaller sample is a broken layout,
not a bound prop.
"""


def binding_sample(
    catalog: dict[str, Any], name: str, prop: str, *, moved: bool = False
) -> dict[str, Any]:
    """A snapshot composing one component with one prop bound to a value.

    Args:
        catalog: The catalog lock: its components and value families.
        name: The component to sample.
        prop: The prop to bind.
        moved: Whether to state the second frame's target instead of the first.

    Returns:
        The snapshot document.
    """
    document = sample(catalog, name)
    spec = catalog["components"][name]["props"][prop]
    target = _target(f"{name}.{prop}", spec, catalog.get("valueTypes", {}))
    if moved:
        target = _moved(target, spec)
    node = _find(document["root"], name)
    node["props"][prop] = {
        "type": "binding",
        "target": target,
        "travel": {"kind": "tween", "durationMs": 100, "delayMs": 0},
        "phase": spec.get("phase", "composition"),
    }
    if isinstance(spec.get("indexOf"), str) and isinstance(target, int):
        # An index is only in range when its slot has a child per index.
        _extend(node, spec["indexOf"], target + 1)
    return document


def _target(where: str, spec: dict[str, Any], values: dict[str, Any]) -> Any:
    """A value the component accepts for this prop, derived from the catalog.

    The component's own default is accepted by definition; a colour of a value
    family crosses the wire only as its tagged object, and a dp prop states a
    height its component can lay out.

    Args:
        where: What is being sampled, for a refusal.
        spec: The prop's lock entry.
        values: The catalog's value families.

    Returns:
        The prop's first-frame value.
    """
    if "default" in spec:
        return spec["default"]
    if "nativeValue" in spec:
        # The size the native default amounts to, which the component accepts by
        # definition, whatever its other props are left at.
        return spec["nativeValue"]
    if spec["type"] == "color" and "valueType" in spec:
        return _tagged_colour(where, spec["valueType"], values)
    if spec["type"] == "dp":
        return DP
    return _value(where, spec, values)


def _tagged_colour(where: str, family: str, values: dict[str, Any]) -> dict[str, Any]:
    """A colour prop's tagged value: the family's own object, at a stated colour.

    Args:
        where: What is being sampled, for the refusal.
        family: The colour family's name.
        values: The catalog's value families.

    Returns:
        The family's tagged object, its packed colour stated.

    Raises:
        ValueError: If the family declares no packed-colour parameter.
    """
    for name, entry in sorted(values.items()):
        if not isinstance(entry, dict) or family not in {name, entry.get("family")}:
            continue
        for parameter, spec in entry.get("parameters", {}).items():
            if spec.get("type") in PACKED and spec.get("required"):
                return {"type": name, parameter: COLOURS[0]}
    raise ValueError(f"{where}: colour family {family} states no packed value")


def _moved(value: Any, spec: dict[str, Any]) -> Any:
    """The same value, moved: a different number, inside the prop's bounds.

    Args:
        value: A valid value of the prop's type.
        spec: The prop's lock entry, for its bounds.

    Returns:
        A different value of the same type, or the value itself when the type
        offers no second one.
    """
    if isinstance(value, bool):
        return not value
    if isinstance(value, dict):
        for name, item in value.items():
            if isinstance(item, int | float) and not isinstance(item, bool):
                return {**value, name: _step(item, spec)}
        return value
    if isinstance(value, int | float) and not isinstance(value, bool):
        return _step(value, spec)
    return value


def _step(value: int | float, spec: dict[str, Any]) -> int | float:
    """The next value inside the prop's bounds, down when already at the top.

    Args:
        value: A valid value of the prop's type.
        spec: The prop's lock entry, for its bounds.

    Returns:
        A different value inside the bounds, or the value itself when the
        bounds leave no room.
    """
    step = 1 if isinstance(value, int) else 1.0
    moved = value + step
    if moved > spec.get("maximum", moved):
        moved = value - step
    top = cast("int | float", spec.get("maximum", moved))
    bottom = cast("int | float", spec.get("minimum", moved))
    return min(max(moved, bottom), top)


def _find(node: dict[str, Any], name: str) -> dict[str, Any]:
    """The sampled component's node: the root, or a provider's slot child.

    Args:
        node: A node of the sample's tree.
        name: The component's catalog name.

    Returns:
        The node composing that component.

    Raises:
        ValueError: If the sample does not compose the component.
    """
    if node.get("type") == name:
        return node
    for child in node.get("children", []):
        if _contains(child, name):
            return _find(child, name)
    raise ValueError(f"the sample of {name} does not compose it")


def _contains(node: dict[str, Any], name: str) -> bool:
    """Whether a node or any of its children composes ``name``.

    Args:
        node: A node of the sample's tree.
        name: The component's catalog name.

    Returns:
        True when the node is found below.
    """
    return node.get("type") == name or any(
        _contains(child, name) for child in node.get("children", [])
    )


def _extend(node: dict[str, Any], slot: str, count: int) -> None:
    """Give a slot as many children as a bound index can name.

    Args:
        node: The component's node, whose children are extended in place.
        slot: The slot the prop indexes.
        count: How many children the slot needs.
    """
    filled = [child for child in node.get("children", []) if child.get("slot") == slot]
    if not filled:
        # A slot the sample does not draw cannot satisfy an index; the host's
        # report says so, which is the honest outcome rather than a fake child.
        return
    for index in range(len(filled), count):
        node.setdefault("children", []).append(
            {**filled[0], "id": f"{node['id']}.{slot}.{index}", "slot": slot}
        )
