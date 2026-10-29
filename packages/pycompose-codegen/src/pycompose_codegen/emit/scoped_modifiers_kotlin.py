"""Kotlin for the modifiers composition scopes declare (``RowScope.weight``).

Each operation applies on the receiver its node's parent lambda carries: the
generated ``ScopedModifiers.apply`` matches the receiver against the scopes
declaring the operation and calls the member there, or returns null when the
node is not inside any of them, which the renderer reports.
"""

from __future__ import annotations

from typing import Any

from pycompose_codegen.emit.literals import GENERATED_NOTICE, kotlin_string
from pycompose_codegen.emit.rules import die
from pycompose_codegen.emit.values import resolver_call

READS = {
    "number": "double",
    "integer": "long",
    "boolean": "boolean",
    "string": "content",
}
"""How a scalar is read off its ``JsonPrimitive``."""

NARROW = {"Float": ".toFloat()", "Int": ".toInt()"}
"""From the wire's Kotlin type (Double, Long) to the parameter's own."""


def _argument(name: str, spec: dict[str, Any], parameter: str) -> str:
    """One named argument, decoded from the operation's JSON."""
    present = f'op.getValue("{name}")'
    if "valueType" in spec:
        decoded = resolver_call(spec["valueType"], present) + ".getOrThrow()"
    elif "decode" in spec:
        decoded = (
            f"com.pycompose.renderer.PropResolver.{spec['decode']}"
            f"({present}.jsonPrimitive.content).getOrThrow()"
        )
    else:
        decoded = f"{present}.jsonPrimitive.{READS[spec['type']]}"
        decoded += NARROW.get(spec.get("nativeType", ""), "")
    if spec.get("required"):
        return f"{parameter} = {decoded}"
    if "default" in spec:
        fallback = (
            kotlin_string(spec["default"])
            if isinstance(spec["default"], str) and "decode" not in spec
            else _literal(spec)
        )
    elif "nativeDefault" in spec:
        fallback = spec["nativeDefault"]
    else:
        die(f"scoped modifier prop {name!r} has no default to fall back on")
    return f'{parameter} = if ("{name}" in op) {decoded} else {fallback}'


def _literal(spec: dict[str, Any]) -> str:
    """A scalar default, spelled as the parameter's Kotlin type."""
    value = spec["default"]
    if "decode" in spec:
        return (
            f"com.pycompose.renderer.PropResolver.{spec['decode']}"
            f"({kotlin_string(value)}).getOrThrow()"
        )
    if isinstance(value, bool):
        return "true" if value else "false"
    if spec.get("nativeType") == "Float":
        return f"{float(value)}f"
    if spec.get("nativeType") == "Int":
        return str(int(value))
    return repr(value)


def render_scoped_modifiers(registry: dict[str, Any]) -> str:
    """Render ``ScopedModifiers.kt``.

    Args:
        registry: The catalog lock.

    Returns:
        The Kotlin source.
    """
    scoped = {
        name: modifier
        for name, modifier in sorted(registry.get("modifiers", {}).items())
        if "scoped" in modifier
    }
    markers = sorted(
        {
            m
            for modifier in scoped.values()
            for s in modifier["scoped"]
            for m in s.get("optIn", ())
        }
    )
    branches = []
    for name, modifier in scoped.items():
        branches += [
            f"            {kotlin_string(name)} ->",
            "                when (scope) {",
        ]
        for declaration in modifier["scoped"]:
            renamed = declaration.get("parameters", {})
            branches += [
                f"                    is {declaration['scope']} ->",
                "                        with(scope) {",
                f"                            Modifier.{declaration['native']}(",
                *(
                    f"                                "
                    f"{_argument(prop, spec, renamed.get(prop, prop))},"
                    for prop, spec in modifier["props"].items()
                ),
                "                            )",
                "                        }",
            ]
        branches += ["                    else -> null", "                }"]
    header = [f"// {GENERATED_NOTICE}"]
    if markers:
        header.append("@file:OptIn(" + ", ".join(f"{m}::class" for m in markers) + ")")
    return "\n".join(
        [
            *header,
            "package com.pycompose.renderer.generated",
            "",
            "import androidx.compose.runtime.Composable",
            "import androidx.compose.ui.Modifier",
            "import kotlinx.serialization.json.JsonObject",
            "import kotlinx.serialization.json.boolean",
            "import kotlinx.serialization.json.double",
            "import kotlinx.serialization.json.jsonPrimitive",
            "import kotlinx.serialization.json.long",
            "",
            "/** Modifiers a composition scope declares, applied on its receiver. */",
            "object ScopedModifiers {",
            "    /** Every scope-declared operation, by wire name. */",
            "    val names: Set<String> =",
            "        setOf(",
            *(f"            {kotlin_string(n)}," for n in scoped),
            "        )",
            "",
            "    /** [type] worn in [scope]; null outside every scope declaring it. */",
            "    @Composable",
            "    fun apply(",
            "        type: String,",
            "        scope: Any?,",
            "        op: JsonObject,",
            "    ): Modifier? =",
            "        when (type) {",
            *branches,
            "            else -> null",
            "        }",
            "}",
            "",
        ]
    )
