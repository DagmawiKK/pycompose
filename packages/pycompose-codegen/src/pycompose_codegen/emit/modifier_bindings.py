"""How generated modifier code reads an argument the app may have bound.

A bound argument is a target the host keeps: the renderer's one ``bindingState``
reads a plain value as it stands and animates a binding through the converter
the pin declares for the prop's Kotlin type, so this module knows no types.
"""

from __future__ import annotations

_BREAK = "\n" + " " * 24


def animated(converter: str, wire: str, decode: str) -> str:
    """An animatable argument read from ``wire``, its ``decode`` reading ``value``.

    Args:
        converter: The Kotlin expression naming the prop type's converter.
        wire: The expression holding the prop's wire value.
        decode: Kotlin reading a plain wire value named ``value``.

    Returns:
        The argument's Kotlin expression.
    """
    return (
        f"com.pycompose.renderer.bindingState({wire}, {converter}) {{ value ->"
        + _BREAK
        + f"{decode} }}.value"
    )
