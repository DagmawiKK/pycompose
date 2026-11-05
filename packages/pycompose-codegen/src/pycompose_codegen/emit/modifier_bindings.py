"""How generated modifier code reads an argument the app may have bound.

A bound argument is a target the host keeps, animated through the converter the
pin declares for the prop's Kotlin type, so this module knows no types.

A prop read in composition passes the renderer's ``bound`` read as the argument:
a plain value as it stands, with no state kept for it. One read in layout or
draw keeps its state (``bindingState``) and reads it inside the lambda the pin
defers it to, so the animation invalidates that phase alone.
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
        f"com.pycompose.renderer.bound({wire}, {converter}) {{ value ->"
        + _BREAK
        + f"{decode} }}"
    )


def deferred(
    name: str, converter: str, wire: str, decode: str, phase: str, *, pure: bool
) -> list[str]:
    """The declaration of a state a deferred lambda reads when it runs.

    A pure decode (a number's, a dp's) reads a live value inside a derived
    state the lambda reads, so a moving stream invalidates that phase alone; a
    decode that reads composition (a colour resolving a theme role) cannot.

    Args:
        name: The prop's wire name; the state is ``<name>State``.
        converter: The Kotlin expression naming the prop type's converter.
        wire: Kotlin for the prop's wire value, which may be absent.
        decode: Kotlin reading a plain wire value named ``value``.
        phase: Where the lambda reads it: ``draw`` or ``layout``.
        pure: Whether the decode reads nothing from composition.

    Returns:
        The declaration's lines, indented for a branch body.
    """
    reader = "deferredState" if pure else "optionalBindingState"
    return [
        f"                val {name}State =",
        f"                    com.pycompose.renderer.{reader}(",
        f"                        {wire}, {converter}, {PHASE}.{phase.title()},",
        f"                    ) {{ value -> {decode} }}",
    ]
