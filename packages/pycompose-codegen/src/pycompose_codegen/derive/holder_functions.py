"""Function arguments of a holder's factory, as the program language types them.

``rememberDrawerState(initialValue, confirmStateChange: (DrawerValue) -> Boolean)``
asks the app whether the drawer may settle at an anchor;
``rememberSwipeToDismissBoxState(positionalThreshold: (totalDistance: Float) -> Float)``
asks how far a swipe must travel. Python cannot answer within the gesture, so
each becomes a ``function`` prop the app fills with a ``@host`` function: its
arguments and answer are scalars, and an argument of the holder's own value
enum arrives as the anchor's wire spelling. Left unset, the factory's own
default answers, so the prop narrows nothing the pin offers.

A parameter qualifies when every argument is a scalar or the value enum, its
answer is a scalar, and the pin states its default in the closed vocabulary.
"""

from __future__ import annotations

from typing import Any

from pycompose_codegen.derive.classpath_types import Declaration, KotlinType

FUNCTION = "kotlin/Function"
SCALARS = {
    "kotlin/Boolean": "boolean",
    "kotlin/Int": "integer",
    "kotlin/Long": "integer",
    "kotlin/Float": "number",
    "kotlin/Double": "number",
}
RENDERED = frozenset({"lambda", "property"})


def factory_functions(
    factory: Declaration, value: str, defaults: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    """Each function argument of a holder's factory the host can ask Python.

    Args:
        factory: The holder's pinned factory.
        value: The holder's value enum, dotted.
        defaults: The factory's compiler-resolved defaults, by parameter.

    Returns:
        Per parameter: its arguments (name, program type, native type), its
        answer's program and native types, and its default.
    """
    enum = value.replace(".", "/")
    functions = {}
    for parameter in factory.parameters:
        kind = parameter.type
        if (
            not _function(kind)
            or defaults.get(parameter.name, {}).get("kind") not in RENDERED
        ):
            continue
        *arguments, answer = (t for _, t in kind.arguments)
        typed = [_typed(t, enum) for t in arguments]
        if answer is None or answer.classifier not in SCALARS or None in typed:
            continue
        functions[parameter.name] = {
            "payload": [
                {
                    "name": _name(t, i),
                    "type": spelled,
                    "native": t.classifier.replace("/", "."),
                }
                for i, (t, spelled) in enumerate(zip(arguments, typed, strict=True))
                if t is not None and spelled is not None
            ],
            "result": SCALARS[answer.classifier],
            "native": answer.classifier.replace("/", "."),
            "default": defaults[parameter.name],
        }
    return functions


def _function(kind: KotlinType) -> bool:
    return (
        kind.classifier.startswith(FUNCTION)
        and kind.classifier[len(FUNCTION) :].isdigit()
        and not kind.nullable
        and not kind.suspend
    )


def _typed(kind: KotlinType | None, enum: str) -> str | None:
    """An argument's program type: a scalar's, or a string for the value enum."""
    if kind is None or kind.nullable:
        return None
    return "string" if kind.classifier == enum else SCALARS.get(kind.classifier)


def _name(kind: KotlinType | None, index: int) -> str:
    """The name the pin gives an argument, else its type's, else its place."""
    named = (
        ((kind.document or {}).get("annotationValues") or {})
        .get("kotlin/ParameterName", {})
        .get("name")
        if kind
        else None
    )
    if isinstance(named, str) and named:
        return named
    simple = kind.classifier.rsplit("/", 1)[1] if kind else ""
    return simple[:1].lower() + simple[1:] if simple else f"argument{index}"
