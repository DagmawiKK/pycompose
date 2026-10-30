"""Bindings: a value the host animates to, with no Python per frame.

Python states where a value should end up and how to travel there; the host
runs the animation with Compose's own ``animate*AsState``, frame by frame, and
restarts it from wherever it is when a later snapshot states a new target. A
binding stands where a modifier takes a number, a dp or a colour.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from pycompose.errors import IrValidationError
from pycompose.model.nodes.props import JsonValue

BINDINGS_SINCE = "1.23.0"
"""The first schema whose envelopes may carry a binding."""


def animatable(prop_type: str, value_type: str | None) -> bool:
    """Whether the host can animate a prop of this type.

    A number, a dp (bare, or its ``Dp`` value) and a colour animate; a family
    built from several dp values, ``PaddingValues`` say, does not.

    Args:
        prop_type: The prop's catalog type.
        value_type: Its value family, if it has one.

    Returns:
        True when a binding may stand for it.
    """
    if prop_type == "dp":
        return value_type in {None, "Dp"}
    return prop_type == "number" or (prop_type == "color" and value_type == "Color")


@dataclass(frozen=True, slots=True)
class Spring:
    """A physical spring, as Compose's ``spring``.

    Attributes:
        damping_ratio: 1 settles without bouncing; below 1 bounces.
        stiffness: How quickly it pulls toward the target.
    """

    damping_ratio: float = 1.0
    stiffness: float = 1500.0

    def to_wire(self) -> dict[str, JsonValue]:
        """Return the spec's wire form.

        Returns:
            ``{"kind": "spring", ...}``.
        """
        return {
            "kind": "spring",
            "dampingRatio": self.damping_ratio,
            "stiffness": self.stiffness,
        }


@dataclass(frozen=True, slots=True)
class Tween:
    """A timed curve, as Compose's ``tween`` with its standard easing.

    Attributes:
        duration_ms: How long the travel takes.
        delay_ms: How long it waits before starting.
    """

    duration_ms: int = 300
    delay_ms: int = 0

    def to_wire(self) -> dict[str, JsonValue]:
        """Return the spec's wire form.

        Returns:
            ``{"kind": "tween", ...}``.
        """
        return {
            "kind": "tween",
            "durationMs": self.duration_ms,
            "delayMs": self.delay_ms,
        }


@dataclass(frozen=True, slots=True)
class Animate:
    """A value the host animates to.

    Attributes:
        to: Where it ends up: a number, or a colour's tagged value.
        spec: How it travels there.
    """

    to: JsonValue
    spec: Spring | Tween

    def to_wire(self) -> dict[str, JsonValue]:
        """Return the binding's wire form.

        Returns:
            ``{"type": "animate", "to": ..., "spec": ...}``.
        """
        return {"type": "animate", "to": self.to, "spec": self.spec.to_wire()}


def lower_binding(value: object) -> JsonValue:
    """A modifier argument as wire data: a binding as its wire form.

    Args:
        value: What the app passed.

    Returns:
        The wire value.
    """
    if isinstance(value, Animate):
        return value.to_wire()
    return cast("JsonValue", value)


def is_binding(value: object) -> bool:
    """Report whether a wire value is a binding.

    Args:
        value: A prop value, possibly frozen.

    Returns:
        True for an ``{"type": "animate", ...}`` object.
    """
    return isinstance(value, Mapping) and value.get("type") == "animate"


def check_binding(value: Mapping[str, object]) -> object:
    """Check a binding's shape and return the target it animates to.

    Args:
        value: The ``{"type": "animate", ...}`` object.

    Returns:
        Its ``to``, for the caller to check against the prop's type.

    Raises:
        IrValidationError: If the spec or the object's keys are not a binding's.
    """
    if set(value) != {"type", "to", "spec"}:
        raise IrValidationError("a binding is {type: animate, to, spec}")
    spec = value["spec"]
    if not isinstance(spec, Mapping):
        raise IrValidationError("a binding's spec is an object")
    numbers = {
        "spring": ("dampingRatio", "stiffness"),
        "tween": ("durationMs", "delayMs"),
    }.get(str(spec.get("kind")))
    if numbers is None or set(spec) != {"kind", *numbers}:
        raise IrValidationError("a binding's spec is a spring or a tween")
    for name in numbers:
        number = spec[name]
        if (
            not isinstance(number, int | float)
            or isinstance(number, bool)
            or not math.isfinite(number)
            or number < 0
        ):
            raise IrValidationError("a binding's spec takes nonnegative numbers")
    return value["to"]
