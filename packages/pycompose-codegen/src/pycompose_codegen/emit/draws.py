"""Codegen for draw calls: the Python a draw function calls, the Kotlin that paints.

The lock's ``draws`` section is the pinned ``DrawScope``'s draw members, each
with the program arguments it takes. Python gets one typed function per call,
which records the call when a draw function runs as Python and which the
compiler recognises by its ``__draw__`` name. Kotlin gets one ``paint`` that
turns a call a program made back into the member call, with the native values
its arguments stand for.
"""

from __future__ import annotations

from typing import Any

from pycompose.model.nodes.props import to_snake_case
from pycompose_codegen.emit.literals import GENERATED_NOTICE

PY_TYPES = {"integer": "int", "number": "float", "boolean": "bool"}


def render_draws_python(registry: dict[str, Any]) -> str:
    """The draw calls a draw function imports from ``pycompose.ui``.

    Args:
        registry: The parsed lock.

    Returns:
        The module source.
    """
    draws = registry.get("draws", {})
    names = {name: to_snake_case(name) for name in draws}
    lines = [
        f"# {GENERATED_NOTICE}",
        '"""Draw calls: one per ``DrawScope`` member the pin declares.',
        "",
        "Call them inside a ``@host`` draw function; run as Python, each records",
        "itself.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "from pycompose.model.programs.recording import record",
        "",
        "__all__ = [",
        *(f'    "{python}",' for python in sorted(names.values())),
        "]",
    ]
    for name, spec in draws.items():
        arguments = spec["arguments"]
        params = []
        for argument in sorted(arguments, key=lambda a: "default" in a):
            annotation = PY_TYPES[argument["type"]]
            default = f" = {argument['default']!r}" if "default" in argument else ""
            params.append(
                f"    {to_snake_case(argument['name'])}: {annotation}{default},"
            )
        lines += [
            "",
            "",
            f"def {names[name]}(",
            *params,
            ") -> None:",
            f'    """Draw with ``DrawScope.{spec["call"]}``.',
            "",
            "    Args:",
            *(
                f"        {to_snake_case(a['name'])}: Its ``{a['native']}``"
                + (" (a colour, ARGB)." if a["type"] == "integer" else ".")
                for a in sorted(arguments, key=lambda a: "default" in a)
            ),
            '    """',
            "    record(",
            f'        "{name}",',
            "        (",
            *(
                f"            {PY_TYPES[a['type']]}({to_snake_case(a['name'])}),"
                for a in arguments
            ),
            "        ),",
            "    )",
            "",
            "",
            f'{names[name]}.__draw__ = "{name}"  # type: ignore[attr-defined]',
        ]
    return "\n".join(lines).rstrip() + "\n"


def render_draws_kotlin(registry: dict[str, Any]) -> str:
    """One ``paint`` mapping each draw call onto its ``DrawScope`` member.

    Args:
        registry: The parsed lock.

    Returns:
        The Kotlin source.
    """
    lines = [
        f"// {GENERATED_NOTICE}",
        "package com.pycompose.renderer.generated",
        "",
        "import androidx.compose.ui.graphics.drawscope.DrawScope",
        "import androidx.compose.ui.graphics.drawscope.Fill",
        "import androidx.compose.ui.graphics.drawscope.Stroke",
        "import com.pycompose.program.DrawCall",
        "",
        "/** Paint one draw call a program made, through the member it names. */",
        "fun DrawScope.paint(call: DrawCall) {",
        "    val a = call.args",
        "    when (call.name) {",
    ]
    for name, spec in registry.get("draws", {}).items():
        lines.append(f'        "{name}" ->')
        lines.append(f"            {spec['call']}(")
        index = {a["name"]: i for i, a in enumerate(spec["arguments"])}
        for native, kotlin_type in spec["native"].items():
            parts = [a for a in spec["arguments"] if a["native"] == native]
            lines.append(
                f"                {native} = {_native(kotlin_type, parts, index)},"
            )
        lines.append("            )")
    lines += [
        '        else -> error("Unknown draw call ${call.name}")',
        "    }",
        "}",
        "",
        "/** A draw program's stroke: 0 fills, and a width strokes. */",
        "private fun style(width: Double) =",
        "    if (width > 0) Stroke(width.toFloat()) else Fill",
        "",
    ]
    return "\n".join(lines)


def _native(
    kotlin_type: str, parts: list[dict[str, Any]], index: dict[str, int]
) -> str:
    """The native value a draw call's arguments stand for."""
    reads = [f"a[{index[part['name']]}]" for part in parts]
    if kotlin_type == "androidx.compose.ui.graphics.Color":
        return f"androidx.compose.ui.graphics.Color(({reads[0]} as Long).toInt())"
    if kotlin_type == "kotlin.Float":
        return f"({reads[0]} as Double).toFloat()"
    if kotlin_type == "kotlin.Boolean":
        return f"{reads[0]} as Boolean"
    if kotlin_type == "androidx.compose.ui.graphics.drawscope.DrawStyle":
        return f"style({reads[0]} as Double)"
    floats = ", ".join(f"({read} as Double).toFloat()" for read in reads)
    # A pair -- Offset, Size, CornerRadius -- from its two numbers.
    return f"{kotlin_type}({floats})"
