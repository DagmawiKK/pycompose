"""Wire-schema emission: ``schema/ir.schema.json`` from the registry.

The wire is a strict projection of the approved catalog (ADR-0003); every
node and prop the emitter offers traces to a registry entry.
"""

import json
import re
from typing import Any

from pycompose_codegen.emit.rules import (
    SLOT_NAME,
    die,
    supported,
    version_key,
)

JSON_SCHEMA_DRAFT = "http://json-schema.org/draft-07/schema#"


def render_ir_schema(registry: dict[str, Any]) -> str:
    """Render the derived JSON Schema for canonical IR snapshots."""
    from pycompose_codegen.emit.values import json_definitions

    components = registry["components"]
    action_ids = sorted(registry.get("actions", {}))
    component_defs = {
        f"C_{name}": _component_schema(name, comp)
        for name, comp in sorted(components.items())
    }
    ir_schema: dict[str, Any] = {
        "$schema": JSON_SCHEMA_DRAFT,
        "$id": "https://pycompose.dev/schema/ir.schema.json",
        "title": "PyCompose IR: canonical snapshot",
        "type": "object",
        "required": ["version", "schemaVersion", "root"],
        "properties": {
            "version": {"type": "string"},
            "schemaVersion": {"enum": supported(registry)},
            "root": {"$ref": "#/definitions/Node"},
        },
        "definitions": {
            "Action": action_schema(action_ids),
            "Node": _node_schema(sorted(component_defs)),
            "ModifierOperation": _modifier_schema(registry),
            # Its shape only; the closed vocabulary, types and limits are the
            # validators' (pycompose/core/expressions.py, Expressions.kt).
            "Expression": {
                "type": "object",
                "required": ["type", "node"],
                "properties": {
                    "type": {"const": "expression"},
                    "node": {"type": "object"},
                },
                "additionalProperties": False,
            },
            **component_defs,
            **json_definitions(registry),
        },
    }
    # Each supported envelope selects its own recursive catalog from the manifest.
    branches = []
    for version in supported(registry):
        prefix = "V_" + version.replace(".", "_") + "_"
        ir_schema["definitions"][prefix + "ModifierOperation"] = _modifier_schema(
            registry, version
        )
        available = {}
        for name, spec in components.items():
            if version_key(spec.get("since", version)) > version_key(version):
                continue
            scoped = {
                **spec,
                "props": {
                    key: {
                        k: v
                        for k, v in prop.items()
                        if k != "valueType" or version_key(version) >= (1, 11, 0)
                    }
                    for key, prop in spec["props"].items()
                    if version_key(prop.get("since", version)) <= version_key(version)
                },
            }
            schema = _component_schema(name, scoped)
            if "modifier" in scoped["props"]:
                schema["properties"]["props"]["properties"]["modifier"]["properties"][
                    "operations"
                ]["items"] = {"$ref": "#/definitions/" + prefix + "ModifierOperation"}
            available[prefix + name] = schema
        node_name = prefix + "Node"
        node_schema = _node_schema(sorted(available))
        node_schema["properties"]["children"]["items"] = {
            "$ref": "#/definitions/" + node_name
        }
        ir_schema["definitions"].update(available)
        ir_schema["definitions"][node_name] = node_schema
        branches.append(
            {
                "if": {"properties": {"schemaVersion": {"const": version}}},
                "then": {
                    "properties": {"root": {"$ref": "#/definitions/" + node_name}}
                },
            }
        )
    ir_schema["allOf"] = branches
    return json.dumps(ir_schema, indent=2, sort_keys=True) + "\n"


def _modifier_schema(
    registry: dict[str, Any], version: str | None = None
) -> dict[str, Any]:
    variants: list[Any] = []
    for name, modifier in sorted(registry.get("modifiers", {}).items()):
        props = modifier["props"]
        if version is not None and any(
            version_key(p.get("since", version)) > version_key(version)
            for p in (modifier, *props.values())
        ):
            continue
        scoped = {
            key: {
                k: v
                for k, v in prop.items()
                if k != "valueType"
                or version is None
                or version_key(version) >= (1, 11, 0)
            }
            for key, prop in props.items()
        }
        variants.append(
            {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "type",
                    *sorted(k for k, p in props.items() if p.get("required")),
                ],
                "properties": {
                    "type": {"const": name},
                    **{k: _prop_schema(p) for k, p in scoped.items()},
                },
            }
        )
    return {"anyOf": variants or [False]}


def _node_schema(component_refs: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["id", "type", "props"],
        "properties": {
            "id": {"type": "string", "minLength": 1},
            "type": {"type": "string"},
            "props": {"type": "object"},
            "slot": {"type": "string", "pattern": SLOT_NAME.pattern},
            "children": {
                "type": "array",
                "items": {"$ref": "#/definitions/Node"},
            },
        },
        "allOf": [
            {"anyOf": [{"$ref": f"#/definitions/{ref}"} for ref in component_refs]}
        ],
    }


def _component_schema(name: str, comp: dict[str, Any]) -> dict[str, Any]:
    props = sorted(comp["props"].items())
    props_schema = {
        "type": "object",
        "properties": {prop_name: _prop_schema(prop) for prop_name, prop in props},
        "additionalProperties": False,
    }
    required = [prop_name for prop_name, prop in props if prop.get("required")]
    if required:
        props_schema["required"] = required

    node_properties: dict[str, object] = {
        "type": {"const": name},
        "props": props_schema,
    }
    children = comp.get("children", {})
    slots = sorted(comp.get("slots", {}))
    if children.get("allowed") or slots:
        child: dict[str, Any] = {}
        if slots:
            child["properties"] = {"slot": {"enum": slots}}
            if not children.get("allowed"):
                child["required"] = ["slot"]
        elif not children.get("allowed"):
            child["properties"] = {"slot": False}
        minimum = children.get("min", 0)
        if minimum and not slots:
            child["minItems"] = minimum
        node_properties["children"] = {"type": "array", "items": child}
    else:
        node_properties["children"] = False
    return {"type": "object", "properties": node_properties}


def _tagged(prop: dict[str, Any], value: dict[str, Any]) -> dict[str, Any]:
    """A value-typed prop's schema: its family's tagged object, or either form."""
    from pycompose_codegen.emit.values import parameter_schema

    tagged = parameter_schema({**prop, "type": "value", "nullable": False})
    if prop["type"] == "value":
        return tagged
    if prop["type"] == "color":
        # One colour form crosses the wire, the tagged value, or an expression
        # over holder streams that evaluates to one.
        return {"anyOf": [tagged, {"$ref": "#/definitions/Expression"}]}
    if prop["type"] == "enum":
        # A named constant crosses as its tagged constant, never its name.
        return tagged
    return {"anyOf": [value, tagged]}


def action_schema(action_ids: list[str]) -> dict[str, Any]:
    """Return the wire shape of an action: a registry action or an app intent.

    An intent names the handler a control calls and the fields it binds. Which
    handlers a snapshot may name, and what their fields hold, is the
    validator's call against the snapshot's contracts, not the wire's shape.

    Args:
        action_ids: The registry's own action names.

    Returns:
        A JSON Schema for one action value.
    """
    intent = {
        "type": "object",
        "required": ["fields", "intent"],
        "additionalProperties": False,
        "properties": {
            "fields": {"type": "object"},
            "intent": {"type": "string", "minLength": 1},
        },
    }
    if not action_ids:
        return intent
    names = "|".join(map(re.escape, action_ids))
    registry = {"type": "string", "pattern": f"^(?:{names})" + r"(?![\s\S])"}
    return {"oneOf": [registry, intent]}


def _prop_schema(prop: dict[str, Any]) -> dict[str, Any]:
    from pycompose_codegen.emit.values import parameter_schema

    ptype = prop["type"]
    basic = {
        "string": "string",
        "color": "string",
        "integer": "integer",
        "durationMs": "integer",
        "number": "number",
        "dp": "number",
        "boolean": "boolean",
        "value": "object",
    }
    if ptype in basic:
        value: dict[str, Any] = (
            parameter_schema({"type": "float"})
            if ptype == "dp"
            else {"type": basic[ptype]}
        )
    elif ptype == "resource":
        native = "|".join(kind for kind in prop["values"] if kind != "asset")
        patterns = []
        if native:
            patterns.append(f"@({native})/[a-z][a-z0-9_]*")
        if "asset" in prop["values"]:
            patterns.append(
                r"@asset/[A-Za-z0-9_-][A-Za-z0-9_.-]*(?:/[A-Za-z0-9_-][A-Za-z0-9_.-]*)*"
            )
        value = {
            "type": "string",
            "pattern": "^(" + "|".join(patterns) + r")(?![\s\S])",
        }
    elif ptype == "enum":
        value = {"enum": sorted(prop["values"])}
    elif ptype == "actionId":
        # One shape for every action prop, stated once under definitions.
        value = {"$ref": "#/definitions/Action"}
    elif ptype == "modifier":
        value = {
            "type": "object",
            "properties": {
                "operations": {
                    "type": "array",
                    "items": {"$ref": "#/definitions/ModifierOperation"},
                }
            },
        }
    else:
        die(f"unsupported prop type {ptype!r}")
    if "default" in prop:
        value["default"] = prop["default"]
    for bound in ("minimum", "maximum"):
        if bound in prop:
            value[bound] = prop[bound]
    if "valueType" in prop:
        value = _tagged(prop, value)
    return {"anyOf": [value, {"type": "null"}]} if prop.get("nullable") else value
