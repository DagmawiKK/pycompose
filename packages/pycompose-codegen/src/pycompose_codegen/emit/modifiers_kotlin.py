"""Kotlin for every modifier operation: ``GeneratedModifiers.apply``.

An operation policy declares calls the ``Modifier`` extension the pin resolved
it to (its ``call``). An operation a composition scope declares
(``RowScope.weight``) applies on the receiver its node's parent lambda carries:
the generated code matches the receiver against the scopes declaring it and
calls the member there, or returns null when the node is not inside any of
them, which the renderer reports.
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


def _resolved(family: str, value: str) -> str:
    return resolver_call(family, value) + ".getOrThrow()"


def _decoded(spec: dict[str, Any], argument: dict[str, Any]) -> str:
    """The Kotlin value one prop of a direct call passes, read from ``value``.

    A family's tagged object goes through its resolver. A dp also rides the wire
    as a bare number (ADR-0036), and an enumerated family as one of its names,
    which the legacy decoder reads.
    """
    if "valueType" in spec:
        family = spec["valueType"]
        if spec["type"] == "dp" and family == "Dp":
            bare = "com.pycompose.renderer.PropResolver.dp(value.jsonPrimitive.double)"
        elif spec["type"] == "enum":
            decoder = family[:1].lower() + family[1:]
            bare = (
                f"com.pycompose.renderer.PropResolver.{decoder}"
                "(value.jsonPrimitive.content)"
            )
        else:
            return _resolved(family, "value")
        return (
            f"if (value is JsonObject) {_resolved(family, 'value')} "
            f"else {bare}.getOrThrow()"
        )
    if spec["type"] == "actionId":
        return "{ dispatch(value.jsonPrimitive.content) }"
    decoded = f"value.jsonPrimitive.{READS[spec['type']]}"
    native = argument["type"].rsplit(".", 1)[-1]
    return decoded + NARROW.get(native, "")


def _direct(name: str, modifier: dict[str, Any]) -> list[str]:
    """The branch of one operation that calls its resolved function."""
    call = modifier["call"]
    function = call["function"].rsplit(".", 1)[-1]
    if "block" in call:
        return _block(name, modifier, function)
    arguments = [
        f"{argument['parameter']} = "
        f'op.getValue("{prop}").let {{ value -> '
        f"{_decoded(modifier['props'][prop], argument)} }}"
        for prop, argument in call["arguments"].items()
    ]
    bare = call.get("bare", {})
    indent = " " * (20 if bare else 16)
    tagged = [
        f"Modifier.{function}(",
        *(f"{indent}    {argument}," for argument in arguments),
        f"{indent})",
    ]
    if not bare:
        return [
            f"            {kotlin_string(name)} ->",
            f"                {tagged[0]}",
            *tagged[1:],
        ]
    if len(bare) > 1:
        die(f"modifier {name!r}: one prop at most may ride the wire bare")
    ((prop, overload),) = bare.items()
    # The bare number calls the overload that takes exactly that Dp.
    return [
        f"            {kotlin_string(name)} ->",
        f'                if (op.getValue("{prop}") is JsonObject) {{',
        f"                    {tagged[0]}",
        *tagged[1:],
        "                } else {",
        f"                    Modifier.{function}({overload['parameter']} = "
        "com.pycompose.renderer.PropResolver"
        f'.dp(op.getValue("{prop}").jsonPrimitive.double).getOrThrow())',
        "                }",
    ]


def _block(name: str, modifier: dict[str, Any], function: str) -> list[str]:
    """The branch of an operation whose call sets members of a receiver block."""
    call = modifier["call"]
    lines = [
        f"            {kotlin_string(name)} ->",
        f"                Modifier.{function}({call['block']['parameter']} = {{",
    ]
    for prop, argument in call["arguments"].items():
        spec = modifier["props"][prop]
        member = argument["source"]["name"]
        if argument["member"] == "function":
            flag = f'op["{prop}"]?.jsonPrimitive?.booleanOrNull == true'
            lines.append(f"                    if ({flag}) {member}()")
            continue
        if "constants" in argument:
            owner = argument["type"]
            lines += [
                f'                    op["{prop}"]?.let {{',
                f"                        {member} =",
                "                            when (it.jsonPrimitive.content) {",
                *(
                    f"                                {kotlin_string(value)} -> "
                    f"{owner}.{constant}"
                    for value, constant in argument["constants"].items()
                ),
                f'                                else -> error("unknown {prop}")',
                "                            }",
                "                    }",
            ]
            continue
        else:
            native = argument["type"].rsplit(".", 1)[-1]
            value = f"it.jsonPrimitive.{READS[spec['type']]}" + NARROW.get(native, "")
        lines.append(f'                    op["{prop}"]?.let {{ {member} = {value} }}')
    return [*lines, "                })"]


def _imports(registry: dict[str, Any]) -> list[str]:
    """What the direct calls name unqualified: their functions and members."""
    names: set[str] = set()
    for modifier in registry.get("modifiers", {}).values():
        call = modifier.get("call")
        if call is None:
            continue
        names.add(call["function"])
        if "block" in call:
            package = call["function"].rsplit(".", 1)[0]
            names.update(
                f"{package}.{argument['source']['name']}"
                for argument in call["arguments"].values()
            )
    return [f"import {name}" for name in sorted(names)]


def render_modifiers(registry: dict[str, Any]) -> str:
    """Render ``GeneratedModifiers.kt``.

    Args:
        registry: The catalog lock.

    Returns:
        The Kotlin source.
    """
    modifiers = registry.get("modifiers", {})
    scoped = {
        name: modifier
        for name, modifier in sorted(modifiers.items())
        if "scoped" in modifier
    }
    direct = [
        line
        for name, modifier in sorted(modifiers.items())
        if "call" in modifier
        for line in _direct(name, modifier)
    ]
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
            *_imports(registry),
            "import kotlinx.serialization.json.JsonObject",
            "import kotlinx.serialization.json.boolean",
            "import kotlinx.serialization.json.booleanOrNull",
            "import kotlinx.serialization.json.double",
            "import kotlinx.serialization.json.jsonPrimitive",
            "import kotlinx.serialization.json.long",
            "",
            "/** Every modifier operation the catalog declares, from its wire form. */",
            "object GeneratedModifiers {",
            "    /**",
            "     * [type] applied with [op]'s props; null for an operation worn",
            "     * outside every scope declaring it. [dispatch] sends a click's id.",
            "     */",
            "    @Composable",
            "    fun apply(",
            "        type: String,",
            "        scope: Any?,",
            "        op: JsonObject,",
            "        dispatch: (String) -> Unit,",
            "    ): Modifier? =",
            "        when (type) {",
            *direct,
            *branches,
            "            else -> null",
            "        }",
            "}",
            "",
        ]
    )
