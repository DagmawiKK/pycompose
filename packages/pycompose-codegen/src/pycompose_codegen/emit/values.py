"""Generate approved value constructors and their pure-data descriptors."""

from __future__ import annotations

import json
import keyword
import textwrap
from typing import Any

from pycompose.core.props import to_snake_case
from pycompose.core.values import FLOAT_MAX, FLOAT_MIN
from pycompose_codegen.emit.defaults import render_default

KINDS = {"scalar", "record", "factory", "constant", "reference", "operator"}


def validate_definitions(registry: dict[str, Any]) -> None:
    """Fail generation on unresolved families or unimplemented behavior policies."""
    from pycompose_codegen.emit.rules import die, require_semver

    specs = definitions(registry)
    families = {s["family"] for s in specs.values()}
    for name, spec in specs.items():
        if not name.isidentifier() or keyword.iskeyword(name):
            die(f"invalid value constructor: {name}")
        if spec.get("kind") not in KINDS:
            die(f"unsupported value policy for {name}")
        _validate_operator(name, spec)
        require_semver(spec.get("since"), f"valueTypes.{name}.since")
        if spec["since"] not in registry["supportedSchemaVersions"]:
            die(f"value {name} requires an unsupported schema")
        markers = spec.get("optIn", [])
        if markers != sorted(set(markers)) or not all(
            isinstance(marker, str) and marker for marker in markers
        ):
            die(f"valueTypes.{name}.optIn must be sorted, unique annotation names")
        _validate_holders(name, spec)
        for field, rule in spec["parameters"].items():
            if not field.isidentifier() or keyword.iskeyword(to_snake_case(field)):
                die(f"invalid value parameter: {name}.{field}")
            _validate_rule(rule, families)
            _validate_default(name, field, rule)
    for section in ("components", "modifiers"):
        for spec in registry.get(section, {}).values():
            for prop in spec["props"].values():
                if "valueType" in prop and prop["valueType"] not in families:
                    die(f"unknown value family: {prop['valueType']}")
                if prop["type"] == "value" and "valueType" not in prop:
                    die("value props need a valueType")


def _validate_operator(name: str, spec: dict[str, Any]) -> None:
    """Fail generation on an operator family without its form or citation.

    The range descriptor is the one family with no artifact to pin: its
    evidence is the language-level operator (ADR-0017 decision 5), so the
    native form drives the emitted expression, and the citation in the
    source is what tells the re-derivation passes to skip the family rather
    than invent a source the compiler never resolved.

    Args:
        name: The value constructor name.
        spec: Its schema entry.
    """
    from pycompose_codegen.emit.rules import die

    if spec.get("kind") != "operator":
        return
    native = spec.get("native") or {}
    if native.get("operator") != "..":
        die(f"value {name}: an operator family needs a native '..'")
    source = spec.get("source") or {}
    if source.get("language") != "kotlin" or source.get("operator") != "..":
        die(f"value {name}: an operator family needs a language-level citation")


def _validate_holders(name: str, spec: dict[str, Any]) -> None:
    """Fail generation when a constant's native holders are not exact."""
    from pycompose_codegen.emit.rules import die

    native = spec.get("native") or {}
    packages = native.get("imports")
    if packages is not None:
        if not isinstance(packages, list) or not all(
            isinstance(package, str) and package and package.replace(".", "").isalnum()
            for package in packages
        ):
            die(f"valueTypes.{name}.native.imports must be dotted packages")
        if packages != sorted(set(packages)):
            die(f"valueTypes.{name}.native.imports must be sorted and unique")
    if "owners" not in native:
        return
    if "propertyOwner" not in native and "constants" not in native:
        die(f"valueTypes.{name}.native.owners needs a default holder")
    owners = native["owners"]
    if not isinstance(owners, dict) or not owners:
        die(f"valueTypes.{name}.native.owners must be a non-empty object")
    values = spec["parameters"][native["constantParameter"]]["values"]
    for member, holder in owners.items():
        if member not in values:
            die(f"valueTypes.{name}.native.owners.{member} is not a value")
        if (
            not isinstance(holder, str)
            or not holder
            or not holder.replace(".", "").replace("$", "").isalnum()
        ):
            die(f"valueTypes.{name}.native.owners.{member} is not a native holder")


def _validate_default(name: str, field: str, rule: dict[str, Any]) -> None:
    """Every optional parameter needs a default; only typed evidence is accepted."""
    from pycompose_codegen.emit.rules import die

    if "default" in rule:
        try:
            render_default(rule["default"], set())
        except ValueError as exc:
            die(f"{name}.{field}: {exc}")
    elif not rule.get("required"):
        die(f"missing native default provider: {name}.{field}")


def _validate_rule(rule: dict[str, Any], families: set[str]) -> None:
    from pycompose_codegen.emit.rules import die

    kind = rule["type"]
    if kind == "value":
        if rule.get("valueType") not in families:
            die(f"unknown value family: {rule.get('valueType')}")
    elif kind == "list":
        _validate_rule(rule["items"], families)
    elif kind not in {"int", "long", "float", "double", "string", "boolean"}:
        die(f"unsupported value scalar: {kind}")


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
            **(
                {"orderedParameters": list(spec["parameters"])}
                if spec["kind"] == "operator"
                else {}
            ),
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


def method_name(family: str) -> str:
    """Name the generated resolver method for one value family.

    Args:
        family: The value family, e.g. ``Sp``.

    Returns:
        The Kotlin method name, e.g. ``sp``.
    """
    return family[:1].lower() + family[1:]


def _parameter_alias(family: str, field: str) -> str:
    """Name the Literal alias for one enumerated value parameter.

    Args:
        family: The owning value family, e.g. ``materialIcon``.
        field: The parameter name, e.g. ``name``.

    Returns:
        The alias the generated annotation refers to, e.g.
        ``_MaterialIconName``.
    """
    return f"_{family[:1].upper() + family[1:]}" f"{field[:1].upper() + field[1:]}"


def resolver_call(family: str, source: str) -> str:
    """Call the generated value resolver for one family over wire data.

    Args:
        family: The value family, e.g. ``Sp``.
        source: The Kotlin expression holding the JSON value.

    Returns:
        Kotlin source evaluating to the native value.
    """
    return (
        f"com.pycompose.renderer.generated.ValueResolver.{method_name(family)}"
        f"({source})"
    )


def render_python(registry: dict[str, Any]) -> str:
    """Generate JSON-only constructors; no native values live in Python."""
    from pycompose_codegen.emit.literals import (
        GENERATED_NOTICE,
        python_adjacent_statements,
    )

    specs = definitions(registry)
    raw = _runtime_contract(registry)
    # An enumerated string parameter annotates with a Literal of the exact
    # vocabulary the runtime validator enforces, so the IDE completes the
    # token list from the same manifest that fail-closes on a wrong token.
    aliases = sorted(
        (_parameter_alias(name, field), rule["values"])
        for name, spec in specs.items()
        for field, rule in spec["parameters"].items()
        if rule["type"] == "string" and rule.get("values")
    )
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
        *(["from typing import Literal"] if aliases else []),
        "",
        "from pycompose.core.props import JsonValue",
        f"from pycompose.core.values import {imports}",
        "",
        "__all__ = [",
        *(f'    "{name}",' for name in specs),
        "]",
        "",
        "DEFINITIONS: dict[str, dict[str, object]] = json.loads(",
        *python_adjacent_statements(raw, indent=4),
        ")",
        "",
        "",
    ]
    for alias, vocabulary in aliases:
        lines.append(f"{alias} = Literal[")
        lines.extend(f"    {json.dumps(value)}," for value in vocabulary)
        lines.extend(["]", "", ""])
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
            if rule["type"] == "string" and rule.get("values"):
                annotation = _parameter_alias(name, field)
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
            for field in ordered:
                lines.extend(
                    textwrap.wrap(
                        f"{to_snake_case(field)}: Native {field} argument.",
                        width=88,
                        initial_indent="        ",
                        subsequent_indent="            ",
                    )
                )
        lines.extend(
            ["", "    Returns:", "        Validated, detached JSON data.", '    """']
        )
        lines.extend(["    return construct(", f'        "{name}",', "        {"])
        for field in ordered:
            entry = f'            "{field}": {to_snake_case(field)},'
            if len(entry) <= 88:
                lines.append(entry)
            else:
                lines.extend(
                    [
                        f'            "{field}": (',
                        f"                {to_snake_case(field)}",
                        "            ),",
                    ]
                )
        lines.extend(["        },", "        DEFINITIONS,", "    )", "", ""])
    return "\n".join(lines).rstrip() + "\n"


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
            schema.update(minimum=-FLOAT_MAX, maximum=FLOAT_MAX)
            schema = {
                "allOf": [
                    schema,
                    {
                        "anyOf": [
                            {"const": 0},
                            {"minimum": FLOAT_MIN},
                            {"maximum": -FLOAT_MIN},
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
