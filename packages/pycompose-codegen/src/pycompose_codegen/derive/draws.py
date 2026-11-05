"""Draw calls: what a host draw program may ask a ``DrawScope`` to do.

``Canvas(onDraw: DrawScope.() -> Unit)`` hands its lambda a scope whose
``draw*`` members paint. A draw program names those members and their
arguments; the pin says which there are, so the vocabulary is derived, never
listed. A member is a draw call when it takes a ``Color`` and every parameter
either has a protocol a program can state or a default the call keeps:

* ``Color`` is an ARGB integer, ``Float`` a number and ``Boolean`` a boolean;
* ``Offset``, ``Size`` and ``CornerRadius`` are two numbers each, named after
  the parameter (``centerX``, ``centerY``);
* ``DrawStyle`` is one number, ``stroke``: 0 fills, and a width strokes.

Everything else -- a brush, a blend mode, a colour filter -- keeps its default,
and a member with a required parameter of that kind is not a draw call. A scalar
whose pinned default is a literal (``alpha = 1f``) keeps it when a program
leaves it out, and so does ``stroke``, whose default ``Fill`` is 0; every other
argument a program states.
"""

from __future__ import annotations

from typing import Any

from pycompose_codegen.derive.classpath_dump import Inventory

DRAW_SCOPE = "androidx/compose/ui/graphics/drawscope/DrawScope"

SCALARS = {
    "androidx/compose/ui/graphics/Color": "integer",
    "kotlin/Float": "number",
    "kotlin/Boolean": "boolean",
}
"""Parameter types a program states as one value."""

PAIRS = {
    "androidx/compose/ui/geometry/Offset": ("X", "Y"),
    "androidx/compose/ui/geometry/Size": ("Width", "Height"),
    "androidx/compose/ui/geometry/CornerRadius": ("X", "Y"),
}
"""Parameter types a program states as two numbers, by the suffixes it names."""

STYLE = "androidx/compose/ui/graphics/drawscope/DrawStyle"


def draws(
    found: Inventory, defaults: dict[tuple[str, str, str], dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Every draw call the pinned ``DrawScope`` declares, by program name.

    Args:
        found: The pinned inventory.
        defaults: Compiler-resolved defaults by JVM identity.

    Returns:
        Per call: its Kotlin member, and each program argument with the native
        parameter it fills.
    """
    table: dict[str, dict[str, Any]] = {}
    for declaration in sorted(found.declarations, key=lambda d: d.jvm_name or d.name):
        receiver = declaration.dispatch_receiver
        if (
            receiver is None
            or receiver.classifier != DRAW_SCOPE
            or not declaration.name.startswith("draw")
            or declaration.document.get("declarationKind") != "function"
            or not any(
                p.type.classifier == "androidx/compose/ui/graphics/Color"
                for p in declaration.parameters
            )
        ):
            continue
        own = defaults.get(
            (
                declaration.owner,
                declaration.jvm_name or "",
                declaration.jvm_descriptor or "",
            ),
            {},
        )
        arguments: list[dict[str, Any]] = []
        for parameter in declaration.parameters:
            classifier = parameter.type.classifier
            if classifier in SCALARS:
                default = own.get(parameter.name) or {}
                literal = (
                    default.get("kind") == "literal"
                    and default.get("value") is not None
                )
                arguments.append(
                    {
                        "name": parameter.name,
                        "type": SCALARS[classifier],
                        "native": parameter.name,
                        **({"default": default["value"]} if literal else {}),
                    }
                )
            elif classifier in PAIRS:
                arguments.extend(
                    {
                        "name": parameter.name + suffix,
                        "type": "number",
                        "native": parameter.name,
                    }
                    for suffix in PAIRS[classifier]
                )
            elif classifier == STYLE:
                arguments.append(
                    {
                        "name": "stroke",
                        "type": "number",
                        "native": "style",
                        "default": 0,
                    }
                )
            elif not parameter.has_default:
                break
        else:
            name = declaration.name.removeprefix("draw")
            table[name[:1].lower() + name[1:]] = {
                "call": declaration.name,
                "arguments": arguments,
                "native": {
                    parameter.name: parameter.type.classifier.replace("/", ".")
                    for parameter in declaration.parameters
                    if parameter.type.classifier in {*SCALARS, *PAIRS, STYLE}
                },
            }
    return dict(sorted(table.items()))
