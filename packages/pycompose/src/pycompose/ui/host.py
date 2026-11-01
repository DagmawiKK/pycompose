"""What runs on the host within a frame: values it animates, functions it calls.

``animate`` stands where a modifier takes a number, a dp or a colour; Python
states the target, and the host travels there frame by frame::

    Modifier().alpha(animate(1.0 if state.shown else 0.0, tween(250)))

``@host`` compiles a function a parameter calls while it draws, which the host
then calls with no Python in the frame::

    @host
    def weekdays(utc_time_millis: int) -> bool:
        return (utc_time_millis // 86_400_000 + 3) % 7 < 5

    DatePicker(selectable_dates=SelectableDates(is_selectable_date=weekdays))
"""

from __future__ import annotations

from collections.abc import Callable

from pycompose.model.nodes.props import JsonValue
from pycompose.model.programs.bindings import Animate, Spring, Tween
from pycompose.model.programs.functions import HostFunction
from pycompose.ui._compile import compile_function

__all__ = ["Animate", "HostFunction", "animate", "host", "spring", "tween"]


def host(function: Callable[..., object]) -> HostFunction:
    """Compile a function for the host to call, as it is defined.

    Raises SyntaxError, at the offending line, for anything outside what a host
    function may say (see ``pycompose.ui._compile``).

    Args:
        function: Annotated with ``int``, ``float`` and ``bool``.

    Returns:
        The host function; it still calls as the Python it was written as.
    """
    return compile_function(function)


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
