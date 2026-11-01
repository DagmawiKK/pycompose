"""What runs on the host within a frame: values it binds, functions it calls.

``animate`` and ``follow`` stand where a prop takes a value Python can compute
once; the host keeps it there frame by frame::

    Modifier().alpha(animate(1.0 if state.shown else 0.0, tween(250)))
    Modifier().shadow(
        8, ambient_color=follow(Stream("nav", "progress").as_alpha("#000000"))
    )

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
from pycompose.model.programs.bindings import Binding, Spring, Tween
from pycompose.model.programs.expressions import Expression
from pycompose.model.programs.functions import HostFunction
from pycompose.ui._compile import compile_function

__all__ = [
    "Binding",
    "HostFunction",
    "animate",
    "follow",
    "host",
    "spring",
    "tween",
]


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


def animate(to: JsonValue | Expression, spec: Spring | Tween | None = None) -> Binding:
    """A value the host animates to whenever a snapshot states a new one.

    Args:
        to: The target: a number, a colour value such as ``Color(...)``, or an
            expression the host evaluates each frame.
        spec: How it travels there; a non-bouncing spring when omitted.

    Returns:
        The binding.
    """
    return Binding(to, spec or Spring())


def follow(target: JsonValue | Expression) -> Binding:
    """A value the host reads from its target every frame, with no travel.

    Args:
        target: What it tracks: a number, a colour, or an expression such as
            ``Stream(...)``.

    Returns:
        The binding.
    """
    return Binding(target)
