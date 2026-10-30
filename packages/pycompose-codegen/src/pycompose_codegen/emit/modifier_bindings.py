"""How generated modifier code reads an argument the app may have bound.

A bound argument is a target the host animates to (``animate``); the renderer's
``animated*`` helpers read a plain value as it stands and animate a binding,
so every animatable argument is read through one by its Kotlin type.
"""

from __future__ import annotations

from pycompose_codegen.emit.rules import die

_BREAK = "\n" + " " * 24
ANIMATE = {
    "Float": "com.pycompose.renderer.animatedFloat({wire}) {{ value ->"
    + _BREAK
    + "{decode} }}",
    "Double": "com.pycompose.renderer.animatedFloat({wire}) {{ value ->"
    + _BREAK
    + "({decode}).toFloat() }}.toDouble()",
    "Dp": "com.pycompose.renderer.animatedDp({wire}) {{ value ->"
    + _BREAK
    + "{decode} }}",
    "Color": "com.pycompose.renderer.animatedColor({wire}) {{ value ->"
    + _BREAK
    + "{decode} }}",
}
"""How the host animates an argument to a binding's target, by its Kotlin type."""


def animated(native: str, wire: str, decode: str) -> str:
    """An animatable argument read from ``wire``, its ``decode`` reading ``value``.

    Args:
        native: The parameter's Kotlin type.
        wire: The expression holding the prop's wire value.
        decode: Kotlin reading a plain wire value named ``value``.

    Returns:
        The argument's Kotlin expression.
    """
    if native not in ANIMATE:
        die(f"an animatable prop of Kotlin type {native} has no animation")
    return ANIMATE[native].format(wire=wire, decode=decode)
