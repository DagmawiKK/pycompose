"""Bindings: a value the host keeps up to date, with no Python per frame.

A binding states a target and how to reach it. Python states it once; the host
does the rest, frame by frame. One wire form covers all of them::

    follow(target)        the value tracks its target every frame
    animate(target, spec) the value travels there with a spring or a tween

A binding also names the phase it is read in. Compose invalidates by phase, so
a value read while drawing redraws only the drawing; the generator resolves the
phase from what the pin offers and writes it here, and an app overrides it only
where it knows better.

One canonical form keeps a binding from stating what it need not: a binding with
no travel, read in composition, *is* its target, so it is written as the target.
``follow(0.5)`` is ``0.5``, and ``follow(Stream(...))`` is the expression itself.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, cast

from pycompose.errors import IrValidationError
from pycompose.model.catalog.props import PropDef
from pycompose.model.nodes.props import JsonValue
from pycompose.model.programs.expressions import Expression

BINDINGS_SINCE = "1.23.0"
"""The first schema whose envelopes may carry a binding."""

Phase = Literal["composition", "layout", "draw"]
"""Where the host reads a bound value, and so what it invalidates."""

PHASES: tuple[Phase, ...] = ("composition", "layout", "draw")
"""Every phase a binding may name. Both validators refuse any other."""


def animatable(prop: PropDef | Mapping[str, object]) -> bool:
    """Whether the catalog gives this prop an animation converter.

    The pin declares one ``TwoWayConverter`` per type Compose can animate, and
    the lock records on each prop the Kotlin type it would be animated as. A
    prop with no recorded type has no converter, and is offered no binding.

    Args:
        prop: A prop's catalog entry, or its parsed definition.

    Returns:
        True when the lock records an animation type for it.
    """
    animation = prop.get("animation") if isinstance(prop, Mapping) else prop.animation
    return isinstance(animation, str)


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


Spec = Spring | Tween
"""How a value travels to its target; ``None`` means it is read live."""


@dataclass(frozen=True, slots=True)
class Binding:
    """A value the host keeps at its target.

    Attributes:
        target: Where it ends up: a number, a colour's tagged value, or an
            expression the host evaluates each frame.
        travel: How it travels there, or ``None`` to follow the target directly.
        phase: Where the host reads it, or ``None`` for the generator's choice.
    """

    target: JsonValue | Expression
    travel: Spec | None = None
    phase: Phase | None = None

    def to_wire(self, resolved: Phase = "composition") -> JsonValue:
        """Return the binding's wire form, or its target when it need not be one.

        Args:
            resolved: The phase the generator chose, used when the app stated none.

        Returns:
            The target itself for a composition-phase follow; otherwise
            ``{"type": "binding", "target": ..., "travel": ..., "phase": ...}``.
        """
        phase = self.phase or resolved
        target = (
            self.target.to_wire()
            if isinstance(self.target, Expression)
            else self.target
        )
        if self.travel is None and phase == "composition":
            # A follow read in composition is the target itself: one intent,
            # one wire form.
            return cast("JsonValue", target)
        return {
            "type": "binding",
            "target": target,
            "travel": {"kind": "none"}
            if self.travel is None
            else self.travel.to_wire(),
            "phase": phase,
        }


def lower_binding(value: object, phase: Phase = "composition") -> JsonValue:
    """A modifier argument as wire data: a binding as its wire form.

    Args:
        value: What the app passed.
        phase: The phase the generator resolved from the catalog.

    Returns:
        The wire value.
    """
    if isinstance(value, Binding):
        return value.to_wire(phase)
    return cast("JsonValue", value)


def is_binding(value: object) -> bool:
    """Report whether a wire value is a binding.

    Args:
        value: A prop value, possibly frozen.

    Returns:
        True for an ``{"type": "binding", ...}`` object.
    """
    return isinstance(value, Mapping) and value.get("type") == "binding"


def check_binding(value: Mapping[str, object]) -> tuple[object, Phase]:
    """Check a binding's shape and return its target and phase.

    Args:
        value: The ``{"type": "binding", ...}`` object.

    Returns:
        Its ``target``, for the caller to check against the prop's type, and the
        phase it names.

    Raises:
        IrValidationError: If the travel or the object's keys are not a binding's.
    """
    if set(value) != {"type", "target", "travel", "phase"}:
        raise IrValidationError("a binding is {type: binding, target, travel, phase}")
    travel = value["travel"]
    if not isinstance(travel, Mapping):
        raise IrValidationError("a binding's travel is an object")
    kind = str(travel.get("kind"))
    numbers = {
        "none": (),
        "spring": ("dampingRatio", "stiffness"),
        "tween": ("durationMs", "delayMs"),
    }.get(kind)
    if numbers is None or set(travel) != {"kind", *numbers}:
        raise IrValidationError("a binding's travel is none, a spring or a tween")
    for name in numbers:
        number = travel[name]
        if (
            not isinstance(number, int | float)
            or isinstance(number, bool)
            or not math.isfinite(number)
            or number < 0
        ):
            raise IrValidationError("a binding's travel takes nonnegative numbers")
    phase = value["phase"]
    if phase not in PHASES:
        raise IrValidationError("a binding's phase is composition, layout or draw")
    return value["target"], cast("Phase", phase)
