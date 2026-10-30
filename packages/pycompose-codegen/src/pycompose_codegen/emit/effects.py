"""The effects the catalog declares, typed on both sides of the bridge.

Python gets one frozen dataclass per effect, which an app emits; Kotlin gets
one ``Effect`` case per effect, decoded from the request the snapshot carried,
so the host's runner is an exhaustive ``when`` over typed fields. What each
effect does on the phone stays the runner's. Both are documented from the
policy's summaries.
"""

from __future__ import annotations

import json
import textwrap
from typing import Any

from pycompose_codegen.emit.literals import GENERATED_NOTICE, kotlin_string
from pycompose_codegen.emit.overloads import python_name
from pycompose_codegen.emit.python_layout import docstring_arg

PYTHON = {"string": "str", "number": "int | float", "integer": "int", "boolean": "bool"}
KOTLIN = {
    "string": "String",
    "number": "Double",
    "integer": "Long",
    "boolean": "Boolean",
}
READS = {
    "string": "contentOrNull",
    "number": "doubleOrNull",
    "integer": "longOrNull",
    "boolean": "booleanOrNull",
}


def _class(kind: str) -> str:
    return kind[:1].upper() + kind[1:]


def _prose(effect: dict[str, Any], indent: str, width: int = 88) -> list[str]:
    """The effect's summary, then its detail as a second paragraph."""
    lines = textwrap.wrap(effect["summary"], width - len(indent) - 3)
    if "detail" in effect:
        lines += ["", *textwrap.wrap(effect["detail"], width - len(indent))]
    return lines


def _python_field(name: str, spec: dict[str, Any]) -> str:
    annotation = PYTHON[spec["type"]]
    if "default" not in spec:
        return f"    {python_name(name)}: {annotation}"
    return f"    {python_name(name)}: {annotation} = {json.dumps(spec['default'])}"


def _python_class(kind: str, effect: dict[str, Any]) -> list[str]:
    payload = effect["payload"]
    prose = _prose(effect, "    ")
    lines = [
        "@dataclass(frozen=True)",
        f"class {_class(kind)}(TypedEffect):",
        f'    """{prose[0]}',
        *(f"    {line}".rstrip() for line in prose[1:]),
        "",
        "    Attributes:",
        "        kind: The registered effect kind.",
    ]
    for name, spec in payload.items():
        lines += [
            line.replace("            ", "        ", 1)
            for line in docstring_arg(python_name(name), spec["description"])
        ]
    # Fields with a default follow those without, as dataclasses require.
    ordered = sorted(payload.items(), key=lambda item: "default" in item[1])
    return [
        *lines,
        '    """',
        "",
        f'    kind: ClassVar[str] = "{kind}"',
        *(_python_field(name, spec) for name, spec in ordered),
        "",
        "",
    ]


def render_python_effects(registry: dict[str, Any]) -> str:
    """Render ``pycompose/app/generated_effects.py``.

    Args:
        registry: The catalog lock.

    Returns:
        The Python source.
    """
    effects = sorted(registry.get("effects", {}).items())
    return (
        "\n".join(
            [
                f"# {GENERATED_NOTICE}",
                '"""The effects the catalog declares: typed requests an app emits."""',
                "",
                "from __future__ import annotations",
                "",
                "from dataclasses import dataclass",
                "from typing import ClassVar",
                "",
                "from pycompose.app.effects import TypedEffect",
                "",
                "__all__ = [",
                *(f'    "{_class(kind)}",' for kind, _ in effects),
                "]",
                "",
                "",
                *(
                    line
                    for kind, effect in effects
                    for line in _python_class(kind, effect)
                ),
            ]
        ).rstrip()
        + "\n"
    )


def _kdoc(text: str) -> str:
    """Text a KDoc comment can hold, its comment markers' slashes escaped.

    ``*/`` would end the comment, and ``/*`` opens a nested one Kotlin expects
    to be closed.
    """
    return text.replace("/*", "&#47;*").replace("*/", "*&#47;")


def _kotlin_case(kind: str, effect: dict[str, Any]) -> list[str]:
    doc = [f"    /** {_kdoc(effect['summary'])} */"]
    payload = effect["payload"]
    if not payload:
        return [*doc, f"    data object {_class(kind)} : Effect", ""]
    return [
        *doc,
        f"    data class {_class(kind)}(",
        *(
            line
            for name, spec in payload.items()
            for line in (
                f"        /** {_kdoc(spec['description'])} */",
                f"        val {name}: {KOTLIN[spec['type']]},",
            )
        ),
        "    ) : Effect",
        "",
    ]


def _kotlin_read(name: str, spec: dict[str, Any]) -> str:
    read = f'request.payload["{name}"]?.jsonPrimitive?.{READS[spec["type"]]}'
    if "default" not in spec:
        return f"{name} = checkNotNull({read})"
    default = spec["default"]
    if isinstance(default, str):
        fallback = kotlin_string(default)
    elif isinstance(default, bool):
        fallback = "true" if default else "false"
    else:
        fallback = repr(default)
    return f"{name} = {read} ?: {fallback}"


def render_kotlin_effects(registry: dict[str, Any]) -> str:
    """Render ``EffectModels.kt`` in ``:ir``'s generated package.

    Args:
        registry: The catalog lock.

    Returns:
        The Kotlin source.
    """
    effects = sorted(registry.get("effects", {}).items())
    branches = []
    for kind, effect in effects:
        if not effect["payload"]:
            branches.append(f'                "{kind}" -> {_class(kind)}')
            continue
        branches += [
            f'                "{kind}" ->',
            f"                    {_class(kind)}(",
            *(
                f"                        {_kotlin_read(name, spec)},"
                for name, spec in effect["payload"].items()
            ),
            "                    )",
        ]
    return "\n".join(
        [
            f"// {GENERATED_NOTICE}",
            "package com.pycompose.ir.generated",
            "",
            "import com.pycompose.ir.EffectRequest",
            "import kotlinx.serialization.json.booleanOrNull",
            "import kotlinx.serialization.json.contentOrNull",
            "import kotlinx.serialization.json.doubleOrNull",
            "import kotlinx.serialization.json.jsonPrimitive",
            "import kotlinx.serialization.json.longOrNull",
            "",
            "/** The effects the catalog declares, each with its payload typed. */",
            "sealed interface Effect {",
            *(line for kind, effect in effects for line in _kotlin_case(kind, effect)),
            "    companion object {",
            "        /** [request] typed; null for a kind the catalog lacks. */",
            "        fun of(request: EffectRequest): Effect? =",
            "            when (request.kind) {",
            *branches,
            "                else -> null",
            "            }",
            "    }",
            "}",
            "",
        ]
    )
