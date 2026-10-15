"""Generate approved value constructors and their pure-data descriptors."""

from __future__ import annotations

import json
import keyword
from typing import Any

from pycompose.core.props import to_snake_case
from pycompose.schema.codegen.defaults import render_default

KINDS = {"scalar", "record", "factory", "constant", "reference"}


def validate_definitions(registry: dict[str, Any]) -> None:
    """Fail generation on unresolved families or unimplemented behavior policies."""
    from pycompose.schema.codegen.main import _die, _require_semver

    specs = definitions(registry)
    families = {s["family"] for s in specs.values()}
    for name, spec in specs.items():
        if not name.isidentifier() or keyword.iskeyword(name):
            _die(f"invalid value constructor: {name}")
        if spec.get("kind") not in KINDS:
            _die(f"unsupported value policy for {name}")
        _require_semver(spec.get("since"), f"valueTypes.{name}.since")
        if spec["since"] not in registry["supportedSchemaVersions"]:
            _die(f"value {name} requires an unsupported schema")
        for field, rule in spec["parameters"].items():
            if not field.isidentifier() or keyword.iskeyword(to_snake_case(field)):
                _die(f"invalid value parameter: {name}.{field}")
            _validate_rule(rule, families)
            _validate_default(name, field, rule)
    for section in ("components", "modifiers"):
        for spec in registry.get(section, {}).values():
            for prop in spec["props"].values():
                if "valueType" in prop and prop["valueType"] not in families:
                    _die(f"unknown value family: {prop['valueType']}")
                if prop["type"] == "value" and "valueType" not in prop:
                    _die("value props need a valueType")


def _validate_default(name: str, field: str, rule: dict[str, Any]) -> None:
    """Every optional parameter needs a default; only typed evidence is accepted."""
    from pycompose.schema.codegen.main import _die

    if "default" in rule:
        try:
            render_default(rule["default"], set())
        except ValueError as exc:
            _die(f"{name}.{field}: {exc}")
    elif not rule.get("required"):
        _die(f"missing native default provider: {name}.{field}")


def _validate_rule(rule: dict[str, Any], families: set[str]) -> None:
    from pycompose.schema.codegen.main import _die

    kind = rule["type"]
    if kind == "value":
        if rule.get("valueType") not in families:
            _die(f"unknown value family: {rule.get('valueType')}")
    elif kind == "list":
        _validate_rule(rule["items"], families)
    elif kind not in {"int", "long", "float", "double", "string", "boolean"}:
        _die(f"unsupported value scalar: {kind}")


def definitions(registry: dict[str, Any]) -> dict[str, Any]:
    """Select implemented descriptors, not historical family declarations."""
    return {
        name: spec
        for name, spec in sorted(registry.get("valueTypes", {}).items())
        if "family" in spec
    }


def _runtime_contract(registry: dict[str, Any]) -> str:
    """Do not duplicate compiler/native metadata in Python and JVM validators."""

    def rule_contract(rule: dict[str, Any]) -> dict[str, Any]:
        return {
            key: rule_contract(value) if key == "items" else value
            for key, value in rule.items()
            if key not in {"defaultNative", "default"}
        }

    specs = {
        name: {
            "family": spec["family"],
            "since": spec["since"],
            "parameters": {
                field: rule_contract(rule) for field, rule in spec["parameters"].items()
            },
        }
        for name, spec in definitions(registry).items()
    }
    return json.dumps(specs, sort_keys=True, separators=(",", ":"))


def dependency_closure(
    registry: dict[str, Any], constructors: frozenset[str] = frozenset()
) -> dict[str, Any]:
    """Select reachable value families, including retained modifier dependencies."""
    specs = definitions(registry)

    def references(value: Any) -> set[str]:
        if isinstance(value, dict):
            found = {value["valueType"]} if "valueType" in value else set()
            return found | set().union(*(references(item) for item in value.values()))
        if isinstance(value, list):
            return set().union(*(references(item) for item in value))
        return set()

    needed = references(registry["components"]) | references(
        registry.get("modifiers", {})
    )
    needed |= {specs[name]["family"] for name in constructors}
    while True:
        dependencies = set().union(
            *(references(s) for s in specs.values() if s["family"] in needed)
        )
        if dependencies <= needed:
            break
        needed |= dependencies
    return {
        name: spec
        for name, spec in registry.get("valueTypes", {}).items()
        if "family" not in spec or spec["family"] in needed
    }


def render_python(registry: dict[str, Any]) -> str:
    """Generate JSON-only constructors; no native values live in Python."""
    from pycompose.schema.codegen.main import GENERATED_NOTICE, _python_string

    specs = definitions(registry)
    raw = _runtime_contract(registry)
    optional = any(
        not p.get("required") for s in specs.values() for p in s["parameters"].values()
    )
    imports = "UNSET, _Unset, construct" if optional else "construct"
    lines = [
        f"# {GENERATED_NOTICE}",
        "# ruff: noqa: N802 -- retain native Compose constructor/factory names.",
        '"""Approved Compose values represented exclusively as JSON data."""',
        "",
        "from __future__ import annotations",
        "",
        "import json",
        "",
        "from pycompose.core.props import JsonValue",
        f"from pycompose.core.values import {imports}",
        "",
        "__all__ = [",
        *(f'    "{name}",' for name in specs),
        "]",
        "",
        "DEFINITIONS: dict[str, dict[str, object]] = json.loads(",
        *("    " + _python_string(raw[i : i + 50]) for i in range(0, len(raw), 50)),
        ")",
        "",
        "",
    ]
    scalar = {
        "int": "int",
        "long": "int",
        "float": "float",
        "double": "float",
        "string": "str",
        "boolean": "bool",
    }
    for name, spec in specs.items():
        params = spec["parameters"]
        lines.append(f"def {name}(")
        ordered = sorted(params, key=lambda key: not params[key].get("required", False))
        for field in ordered:
            rule = params[field]
            annotation = scalar.get(rule["type"], "JsonValue")
            if rule.get("nullable"):
                annotation += " | None"
            default = ""
            if not rule.get("required"):
                annotation += " | _Unset"
                default = " = UNSET"
            lines.append(f"    {to_snake_case(field)}: {annotation}{default},")
        lines.extend(
            [
                ") -> dict[str, JsonValue]:",
                f'    """Construct {spec["family"]} data for native evaluation.',
            ]
        )
        if params:
            lines.extend(["", "    Args:"])
            lines.extend(
                f"        {to_snake_case(p)}: Native {p} argument." for p in ordered
            )
        lines.extend(
            ["", "    Returns:", "        Validated, detached JSON data.", '    """']
        )
        lines.extend(["    return construct(", f'        "{name}",', "        {"])
        lines.extend(f'            "{p}": {to_snake_case(p)},' for p in ordered)
        lines.extend(["        },", "        DEFINITIONS,", "    )", "", ""])
    return "\n".join(lines).rstrip() + "\n"


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


def render_models(registry: dict[str, Any]) -> str:
    """Generate pure JVM sealed wire models and typed readers."""
    from pycompose.schema.codegen.main import GENERATED_NOTICE, _kt_string

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
            '    const val SCHEMA_VERSION = "1.11.0"',
            '    private val json = Json { classDiscriminator = "type" }',
            "    val specs: JsonObject = json.parseToJsonElement(",
        ]
    )
    raw = _runtime_contract(registry)
    chunks = [raw[i : i + 60] for i in range(0, len(raw), 60)]
    lines.extend(
        "        " + _kt_string(chunk) + (" +" if i < len(chunks) - 1 else "")
        for i, chunk in enumerate(chunks)
    )
    lines.extend(["    ).jsonObject", ""])
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
                    f"            {_kt_string(name)} -> Wire{name}(",
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


def render_native(registry: dict[str, Any]) -> str:
    """Generate native calls from approved factory descriptions."""
    from pycompose.schema.codegen.main import GENERATED_NOTICE

    specs = definitions(registry)
    families = sorted({s["family"] for s in specs.values()})
    imports: set[str] = set()
    defaults = {
        (name, field): render_default(rule["default"], imports)
        for name, spec in specs.items()
        for field, rule in spec["parameters"].items()
        if "default" in rule
    }
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
        native_type = next(
            s["kotlinType"] for s in specs.values() if s["family"] == family
        )
        method = family[:1].lower() + family[1:]
        lines.extend(
            [
                "    @Composable",
                f"    fun {method}(value: JsonElement): Result<{native_type}> {{",
                "        val parsed = runCatching { "
                f"ValueContract.read{family}(value) }}"
                ".getOrElse { return Result.failure(it) }",
                f"        return Result.success({method}(parsed))",
                "    }",
                "",
                "    @Composable",
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
                choices = native.get("constants") or {
                    key: native["propertyOwner"] + "." + key
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
        return f"{family[:1].lower() + family[1:]}({source})"
    if kind == "list":
        converted = _decode_parameter("element", rule["items"])
        return f"{source}.map {{ element -> {converted} }}"
    return source + (".toFloat()" if kind == "float" else "")


def json_definitions(registry: dict[str, Any]) -> dict[str, Any]:
    """Generate strict recursive value schemas for the canonical IR validator."""
    specs = definitions(registry)
    output = {}
    for name, spec in specs.items():
        output["Value_" + name] = {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "type",
                *[p for p, r in spec["parameters"].items() if r.get("required")],
            ],
            "properties": {
                "type": {"const": name},
                **{p: parameter_schema(r) for p, r in spec["parameters"].items()},
            },
        }
    for family in sorted({s["family"] for s in specs.values()}):
        output["Family_" + family] = {
            "oneOf": [
                {"$ref": "#/definitions/Value_" + n}
                for n, s in specs.items()
                if s["family"] == family
            ]
        }
    return output


def parameter_schema(rule: dict[str, Any]) -> dict[str, Any]:
    if rule["type"] == "value":
        schema = {"$ref": "#/definitions/Family_" + rule["valueType"]}
        bounds = {key: rule[key] for key in ("minimum", "maximum") if key in rule}
        if bounds:
            schema = {"allOf": [schema, {"properties": {"value": bounds}}]}
    elif rule["type"] == "list":
        schema = {
            "type": "array",
            "items": parameter_schema(rule["items"]),
            "minItems": rule.get("minItems", 0),
        }
    else:
        scalar = {
            "int": "integer",
            "long": "integer",
            "float": "number",
            "double": "number",
            "string": "string",
            "boolean": "boolean",
        }
        schema = {"type": scalar[rule["type"]]}
        if rule["type"] in {"int", "long"}:
            bits = 32 if rule["type"] == "int" else 64
            schema.update(minimum=-(2 ** (bits - 1)), maximum=2 ** (bits - 1) - 1)
        if rule["type"] == "float":
            schema.update(minimum=-3.4028234663852886e38, maximum=3.4028234663852886e38)
            schema = {
                "allOf": [
                    schema,
                    {
                        "anyOf": [
                            {"const": 0},
                            {"minimum": 1.401298464324817e-45},
                            {"maximum": -1.401298464324817e-45},
                        ]
                    },
                ]
            }
        if "values" in rule:
            schema["enum"] = rule["values"]
        for bound in ("minimum", "maximum"):
            if bound in rule:
                schema[bound] = rule[bound]
    return {"anyOf": [schema, {"type": "null"}]} if rule.get("nullable") else schema
