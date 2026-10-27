"""Kotlin-side renderers for the approved value families."""

from __future__ import annotations

from typing import Any

from pycompose.codegen.defaults import render_default
from pycompose.codegen.values import (
    _runtime_contract,
    definitions,
    method_name,
)


def _kt_type(rule: dict[str, Any]) -> str:
    if rule["type"] == "value":
        return str(rule["valueType"]) + "Value"
    if rule["type"] == "list":
        return f"List<{_kt_type(rule['items'])}>"
    return {
        "int": "Int",
        "long": "Long",
        "float": "Double",
        "double": "Double",
        "string": "String",
        "boolean": "Boolean",
    }[rule["type"]]


def _native_type(spec: dict[str, Any]) -> str:
    """The Kotlin type one family's resolver hands back.

    The pin spells a generic family as its raw class, so the one family whose
    type argument no artifact pins adds it here: an operator form builds its
    value from decoded operands, and ``start..end`` is a range of exactly the
    endpoint type -- a float operand is narrowed by its decode and lands as
    ``Float`` where the wire field carried a double.

    Args:
        spec: One descriptor of the family.

    Returns:
        The family's Kotlin type, parameterized where its form binds operands.
    """
    if spec["kind"] != "operator":
        return str(spec["kotlinType"])
    first = spec["parameters"][next(iter(spec["parameters"]))]
    operand = "Float" if first["type"] == "float" else _kt_type(first)
    return f"{spec['kotlinType']}<{operand}>"


def render_models(registry: dict[str, Any]) -> str:
    """Generate pure JVM sealed wire models and typed readers."""
    from pycompose.codegen.literals import (
        GENERATED_NOTICE,
        kotlin_joined_statements,
        kotlin_string,
    )

    specs = definitions(registry)
    families = sorted({s["family"] for s in specs.values()})
    lines = [
        f"// {GENERATED_NOTICE}",
        "package com.pycompose.ir.generated",
        "",
        "import com.pycompose.ir.ValueParser",
        "import kotlinx.serialization.json.Json",
        "import kotlinx.serialization.json.JsonElement",
        "import kotlinx.serialization.json.JsonObject",
        "import kotlinx.serialization.json.JsonArray",
        "import kotlinx.serialization.json.JsonNull",
        "import kotlinx.serialization.json.jsonPrimitive",
        "import kotlinx.serialization.json.int",
        "import kotlinx.serialization.json.long",
        "import kotlinx.serialization.json.double",
        "import kotlinx.serialization.json.boolean",
        "import kotlinx.serialization.json.jsonObject",
        "",
    ]
    for family in families:
        lines.extend([f"sealed interface {family}Value", ""])
    for name, spec in specs.items():
        lines.append(f"data class Wire{name}(")
        lines.append("    val supplied: Set<String>,")
        for field, rule in spec["parameters"].items():
            nullable = not rule.get("required") or rule.get("nullable")
            suffix = "?" if nullable else ""
            default = " = null" if not rule.get("required") else ""
            lines.append(f"    val {field}: {_kt_type(rule)}{suffix}{default},")
        lines.extend([f") : {spec['family']}Value", ""])
    lines.extend(
        [
            "object ValueContract {",
            f'    const val SCHEMA_VERSION = "{registry["schemaVersion"]}"',
            '    private val json = Json { classDiscriminator = "type" }',
            "    val specs: JsonObject = json.parseToJsonElement(",
        ]
    )
    raw = _runtime_contract(registry)
    # One flat list, joined once. Concatenating the pieces with `+` is the same
    # string to Kotlin's runtime, but every link is a call on the previous
    # result, so the resolver recurses once per chunk and a long contract
    # overflows its stack before the file even type-checks.
    lines.extend(
        [
            "        // Joined from a flat list: a chain of + this long overflows",
            "        // the compiler's stack.",
            "        listOf(",
        ]
    )
    lines.extend(kotlin_joined_statements(raw))
    lines.extend(['        ).joinToString(""),', "    ).jsonObject", ""])
    for family in families:
        lines.extend(
            [
                f"    fun read{family}(value: JsonElement): {family}Value {{",
                f'        ValueParser.validate(value, "{family}", specs).getOrThrow()',
                "        val data = value.jsonObject",
                '        return when (data.getValue("type").jsonPrimitive.content) {',
            ]
        )
        for name, spec in specs.items():
            if spec["family"] != family:
                continue
            lines.extend(
                [
                    f"            {kotlin_string(name)} -> Wire{name}(",
                    "                supplied = data.keys,",
                ]
            )
            for field, rule in spec["parameters"].items():
                source = f'data.getValue("{field}")'
                expression = _read_parameter(source, rule)
                if not rule.get("required") or rule.get("nullable"):
                    expression = (
                        f'data["{field}"]?.takeUnless {{ it == JsonNull }}'
                        f'?.let {{ item -> {_read_parameter("item", rule)} }}'
                    )
                lines.append(f"                {field} = {expression},")
            lines.append("            )")
        lines.extend(
            [
                '            else -> error("Unknown value constructor")',
                "        }",
                "    }",
                "",
            ]
        )
    return "\n".join([*lines, "}", ""])


def _read_parameter(source: str, rule: dict[str, Any]) -> str:
    kind = rule["type"]
    if kind == "value":
        return f'read{rule["valueType"]}({source})'
    if kind == "list":
        conversion = _read_parameter("element", rule["items"])
        return f"({source} as JsonArray).map {{ element -> {conversion} }}"
    conversion = {
        "int": "int",
        "long": "long",
        "float": "double",
        "double": "double",
        "string": "content",
        "boolean": "boolean",
    }[kind]
    return f"{source}.jsonPrimitive.{conversion}"


def vocabulary_imports(specs: dict[str, dict[str, Any]]) -> set[str]:
    """Collect the packages a constant vocabulary's members are declared in.

    An extension property resolves only where it is declared, and Kotlin cannot
    name one where it stands, so the declaring packages are imported wholesale:
    the pin decides how many members a style carries. The unit extensions get
    the same treatment, one import at a time.

    Args:
        specs: Every approved value descriptor, keyed by constructor name.

    Returns:
        The import lines, empty when no vocabulary is carried that way.
    """
    imports: set[str] = set()
    for spec in specs.values():
        native = spec["native"]
        if "constants" in native or "propertyOwner" in native:
            imports.update(f"import {pkg}.*" for pkg in native.get("imports", []))
    return imports


def render_native(registry: dict[str, Any]) -> str:
    """Generate native calls from approved factory descriptions."""
    from pycompose.codegen.literals import GENERATED_NOTICE

    specs = definitions(registry)
    families = sorted({s["family"] for s in specs.values()})
    imports: set[str] = set()
    defaults = {
        (name, field): render_default(rule["default"], imports)
        for name, spec in specs.items()
        for field, rule in spec["parameters"].items()
        if "default" in rule
    }
    imports.update(vocabulary_imports(specs))
    lines = [
        f"// {GENERATED_NOTICE}",
        "package com.pycompose.renderer.generated",
        "",
        "import androidx.compose.runtime.Composable",
        "import androidx.compose.ui.unit.sp",
        "import androidx.compose.ui.unit.em",
        *sorted(imports),
        "import kotlinx.serialization.json.JsonElement",
        *(f"import com.pycompose.ir.generated.{f}Value" for f in families),
        "import com.pycompose.ir.generated.ValueContract",
        *(f"import com.pycompose.ir.generated.Wire{n}" for n in specs),
        "",
        "object ValueResolver {",
    ]
    for family in families:
        native_type = _native_type(
            next(s for s in specs.values() if s["family"] == family)
        )
        method = method_name(family)
        markers = sorted(
            {
                marker
                for spec in specs.values()
                if spec["family"] == family
                for marker in spec.get("optIn", [])
            }
        )
        opt_in = (
            [f"    @OptIn({', '.join(f'{m}::class' for m in markers)})"]
            if markers
            else []
        )
        lines.extend(
            [
                "    @Composable",
                *opt_in,
                f"    fun {method}(value: JsonElement): Result<{native_type}> {{",
                "        val parsed = runCatching { "
                f"ValueContract.read{family}(value) }}"
                ".getOrElse { return Result.failure(it) }",
                f"        return Result.success({method}(parsed))",
                "    }",
                "",
                "    @Composable",
                *opt_in,
                f"    fun {method}(value: {family}Value): {native_type} =",
                "        when (value) {",
            ]
        )
        for name, spec in specs.items():
            if spec["family"] != family:
                continue
            native = spec["native"]
            lines.append(f"            is Wire{name} -> {{")
            if "constants" in native or "propertyOwner" in native:
                # A vocabulary can live on several holders; a member without an
                # entry reads through the family's default holder.
                holders = native.get("owners") or {}
                choices = native.get("constants") or {
                    key: holders.get(key, native["propertyOwner"]) + "." + key
                    for key in spec["parameters"][native["constantParameter"]]["values"]
                }
                lines.append(
                    f"                when (value.{native['constantParameter']}) {{"
                )
                lines.extend(
                    f'                    "{k}" -> {v}' for k, v in choices.items()
                )
                lines.extend(
                    [
                        '                    else -> error("Unknown native constant")',
                        "                }",
                    ]
                )
            elif "extension" in native:
                lines.append(
                    f"                value.value.toFloat().{native['extension']}"
                )
            elif "constant" in native:
                lines.append(f"                {native['constant']}")
            elif "operator" in native:
                # The one family with no factory to pin builds its value from
                # the operator form itself: start..end over the wire operands.
                operands = [
                    _decode_parameter(f"value.{field}", rule)
                    for field, rule in spec["parameters"].items()
                ]
                expression = native["operator"].join(operands)
                lines.append(f"                {expression}")
            else:
                lines.append(f"                {native['call']}(")
                for field, rule in spec["parameters"].items():
                    source = f"value.{field}"
                    if not rule.get("required") or rule.get("nullable"):
                        converted = _decode_parameter("item", rule)
                        expression = f"{source}?.let {{ item -> {converted} }}"
                    else:
                        expression = _decode_parameter(source, rule)
                    if not rule.get("required"):
                        fallback = defaults[name, field]
                        present = expression + ("" if rule.get("nullable") else "!!")
                        expression = (
                            f'if ("{field}" in value.supplied) '
                            f"{present} else {fallback}"
                        )
                    lines.append(f"                    {field} = {expression},")
                lines.append("                )")
            lines.append("            }")
        lines.extend(["        }", ""])
    return "\n".join([*lines, "}", ""])


def _decode_parameter(source: str, rule: dict[str, Any]) -> str:
    kind = rule["type"]
    if kind == "value":
        family = rule["valueType"]
        return f"{method_name(family)}({source})"
    if kind == "list":
        converted = _decode_parameter("element", rule["items"])
        return f"{source}.map {{ element -> {converted} }}"
    return source + (".toFloat()" if kind == "float" else "")
