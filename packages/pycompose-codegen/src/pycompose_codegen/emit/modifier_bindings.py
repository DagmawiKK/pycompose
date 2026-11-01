"""How generated modifier code reads an argument the app may have bound.

A bound argument is a target the host keeps: the renderer's one ``bindingState``
reads a plain value as it stands and animates a binding through the converter
the pin declares for the prop's Kotlin type, so this module knows no types.

A prop read in composition passes ``.value`` as the argument. One read in
layout or draw keeps its state and reads it inside the lambda the pin defers
it to, so the animation invalidates that phase alone.
"""

from __future__ import annotations

_BREAK = "\n" + " " * 24

PHASE = "com.pycompose.program.Phase"
"""The renderer's closed phase vocabulary, as generated code names it."""


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


def deferred(
    name: str, converter: str, wire: str, decode: str, phase: str
) -> list[str]:
    """The declaration of a state a deferred lambda reads when it runs.

    Args:
        name: The prop's wire name; the state is ``<name>State``.
        converter: The Kotlin expression naming the prop type's converter.
        wire: Kotlin for the prop's wire value, which may be absent.
        decode: Kotlin reading a plain wire value named ``value``.
        phase: Where the lambda reads it: ``draw`` or ``layout``.

    Returns:
        The declaration's lines, indented for a branch body.
    """
    return [
        f"                val {name}State =",
        "                    com.pycompose.renderer.optionalBindingState(",
        f"                        {wire}, {converter}, {PHASE}.{phase.title()},",
        f"                    ) {{ value -> {decode} }}",
    ]
