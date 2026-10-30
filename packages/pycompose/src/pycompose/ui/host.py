"""What runs on the host within a frame: values it animates on its own.

``animate`` stands where a modifier takes a number, a dp or a colour; Python
states the target, and the host travels there frame by frame::

    Modifier().alpha(animate(1.0 if state.shown else 0.0, tween(250)))
"""

from __future__ import annotations

from pycompose.model.nodes.props import JsonValue
from pycompose.model.programs.bindings import Animate, Spring, Tween

__all__ = ["Animate", "animate", "spring", "tween"]


def spring(damping_ratio: float = 1.0, stiffness: float = 1500.0) -> Spring:
    """A physical spring, as Compose's ``spring``.

    Args:
        damping_ratio: 1 settles without bouncing; below 1 bounces.
        stiffness: How quickly it pulls toward the target.

    Returns:
        The spec.
    """
    return Spring(damping_ratio, stiffness)


def tween(duration_ms: int = 300, delay_ms: int = 0) -> Tween:
    """A timed curve, as Compose's ``tween`` with its standard easing.

    Args:
        duration_ms: How long the travel takes.
        delay_ms: How long it waits before starting.

    Returns:
        The spec.
    """
    return Tween(duration_ms, delay_ms)


def animate(to: JsonValue, spec: Spring | Tween | None = None) -> Animate:
    """A value the host animates to whenever a snapshot states a new one.

    Args:
        to: The target: a number, or a colour value such as ``Color(...)``.
        spec: How it travels there; a non-bouncing spring when omitted.

    Returns:
        The binding.
    """
    return Animate(to, spec or Spring())
