"""Kotlin emission: ``:ir`` wire models, the contract registry and host adapters.

Covers :mod:`UiModels`, IrContract's component registry table, and the host's
GeneratedAdapters so every approved component gets performance-tuned wiring.
"""

import re
from typing import Any

from pycompose_codegen.emit.literals import GENERATED_NOTICE, kotlin_string
from pycompose_codegen.emit.rules import die, supported, version_key


def _kt_field(name: str) -> str:
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) is None:
        die(f"invalid Kotlin contract identifier: {name!r}")
    return f"`{name}`"


def _kt_type(prop: dict[str, Any]) -> str:
    if prop.get("nullable") and not prop.get("required"):
        return "OptionalValue"
    suffix = "?" if prop.get("nullable") else ""
    if "valueType" in prop:
        return "JsonElement" + suffix
    return {
        "string": "String",
        "color": "String",
        "resource": "String",
        "actionId": "String",
        "enum": "String",
        "boolean": "Boolean",
        "integer": "Long",
        "durationMs": "Long",
        "number": "Double",
        "dp": "Double",
        "modifier": "JsonObject",
    }[prop["type"]] + suffix


def _modelled_default(prop: dict[str, Any]) -> bool:
    """Whether the model holds the prop's default; a named constant's is native.

    An app names a constant by string, but the wire carries it tagged, so an
    absent one stays absent in the model and the adapter applies the native
    default it declares.
    """
    return "default" in prop and not (prop["type"] == "enum" and "valueType" in prop)


def _kt_default(prop: dict[str, Any]) -> str:
    if prop.get("nullable"):
        return "" if prop.get("required") else " = OptionalValue.Absent"
    if not _modelled_default(prop):
        return "" if prop.get("required", False) else " = null"
    value = prop["default"]
    if "valueType" in prop:
        return f" = JsonPrimitive({kotlin_string(value)})"
    if isinstance(value, str | bool):
        return " = " + (
            kotlin_string(value) if isinstance(value, str) else str(value).lower()
        )
    if prop["type"] in {"integer", "durationMs"}:
        return f" = {value}L"
    if prop["type"] in {"number", "dp"}:
        return f" = {float(value)}"
    die("unsupported Kotlin prop default")


def _kt_props(name: str, props: dict[str, Any], base: str = "UiProps") -> list[str]:
    lines = ["@Serializable"]
    if not props:
        return [*lines, f"data object {name} : {base}", ""]
    lines.append(f"data class {name}(")
    for field, prop in sorted(props.items()):
        nullable = (
            "?"
            if not prop.get("nullable")
            and not prop.get("required", False)
            and not _modelled_default(prop)
            else ""
        )
        override = "override " if field == "modifier" and base == "UiProps" else ""
        lines.append(
            f"    {override}val {_kt_field(field)}: "
            f"{_kt_type(prop)}{nullable}{_kt_default(prop)},"
        )
    return [*lines, f") : {base}", ""]


def render_generated_adapters(registry: dict[str, Any]) -> str:
    """Emit every Kotlin adapter the schema derives, as one always-present object.

    Args:
        registry: The parsed schema.

    Returns:
        The generated Kotlin source.
    """
    from pycompose_codegen.emit.adapters.assemble import render_file

    return render_file(registry)


def render_kotlin_models(registry: dict[str, Any]) -> str:
    """Generate sealed per-component models without Android types or reflection."""
    lines = [
        f"// {GENERATED_NOTICE}",
        "package com.pycompose.ir.generated",
        "",
        "import kotlinx.serialization.SerialName",
        "import kotlinx.serialization.Serializable",
        "import kotlinx.serialization.json.JsonObject",
        "import kotlinx.serialization.json.JsonElement",
        "import kotlinx.serialization.json.JsonPrimitive",
        "import com.pycompose.ir.OptionalValue",
        "",
        "@Serializable",
        "sealed interface UiNode {",
        "    val id: String",
        "    val props: UiProps",
        "    val children: List<UiNode>",
        "    val componentType: String",
        "",
        "    /** Slot this node fills in its parent; null is the primary slot. */",
        "    val slot: String? get() = null",
        "",
        "    /** This node with [children] decoded apart; a leaf has none. */",
        "    fun withChildren(children: List<UiNode>): UiNode",
        "}",
        "",
        "sealed interface UiProps {",
        "    val modifier: JsonObject? get() = null",
        "}",
        "",
        "@Serializable",
        "data class IRRoot(",
        "    val version: String,",
        "    val schemaVersion: String,",
        "    val root: UiNode,",
        "    val metadata: JsonObject? = null,",
        ")",
        "",
    ]
    names = set(registry["components"])
    generated_names = {"UiNode", "UiProps", "IRRoot", "ActionPayload"} | {
        name + "Props" for name in names
    }
    if names & generated_names:
        die("component names collide with generated Kotlin contract types")
    for name, spec in sorted(registry["components"].items()):
        if re.fullmatch(r"[A-Z][A-Za-z0-9_]*", name) is None:
            die(f"component name must be PascalCase for Kotlin generation: {name!r}")
        _kt_field(name)
        lines.extend(_kt_props(name + "Props", spec["props"]))
        lines.extend(
            [
                "@Serializable",
                f"@SerialName({kotlin_string(name)})",
                f"data class {name}(",
                "    override val id: String,",
                f"    override val props: {name}Props,",
            ]
        )
        if spec["children"]["allowed"] or spec.get("slots"):
            # Slot children ride the same list as primary ones, so a component
            # that declares slots carries children even when it forbids primary
            # ones -- a chip's leading icon is a child, not a prop.
            lines.append("    override val children: List<UiNode> = emptyList(),")
        lines.append("    override val slot: String? = null,")
        lines.append(") : UiNode {")
        if not spec["children"]["allowed"] and not spec.get("slots"):
            lines.append("    override val children: List<UiNode> get() = emptyList()")
            lines.append(
                "    override fun withChildren(children: List<UiNode>): UiNode = this"
            )
        else:
            lines.append(
                "    override fun withChildren(children: List<UiNode>): UiNode ="
                " copy(children = children)"
            )
        lines.extend(
            [
                f"    override val componentType: String get() = {kotlin_string(name)}",
                "}",
                "",
            ]
        )
    lines.extend(["sealed interface ActionPayload", ""])
    payload_names: set[str] = set()
    for action, spec in sorted(registry["actions"].items()):
        name = (
            "".join(
                part[:1].upper() + part[1:]
                for part in re.findall(r"[A-Za-z0-9]+", action)
            )
            + "Payload"
        )
        _kt_field(name)
        if name in names | generated_names | payload_names:
            die("action ids must produce unique Kotlin payload names")
        payload_names.add(name)
        lines.extend(_kt_props(name, spec.get("payload", {}), "ActionPayload"))
    return "\n".join(lines)


def _kt_streams(registry: dict[str, Any]) -> list[str]:
    """Render the expression vocabulary and which components expose which streams.

    Args:
        registry: The parsed schema.

    Returns:
        Kotlin source lines.
    """
    from pycompose.contract.registry_vocabulary import (
        EXPRESSION_LIMITS,
        EXPRESSION_OPS,
        STATE_STREAMS,
    )

    exposing = {
        name: STATE_STREAMS[spec["state"]["kind"]]
        for name, spec in sorted(registry["components"].items())
        if spec.get("state", {}).get("kind") in STATE_STREAMS
    }
    return [
        "    val streams: Map<String, Set<String>> = mapOf(",
        *(
            f"        {kotlin_string(name)} to setOf("
            + ", ".join(kotlin_string(stream) for stream in streams)
            + "),"
            for name, streams in exposing.items()
        ),
        "    )",
        "    val streamNames: Set<String> = setOf("
        + ", ".join(
            kotlin_string(name)
            for name in sorted({n for names in STATE_STREAMS.values() for n in names})
        )
        + ")",
        "    val expressionOps: Set<String> = setOf("
        + ", ".join(kotlin_string(op) for op in EXPRESSION_OPS)
        + ")",
        f"    const val EXPRESSION_DEPTH = {EXPRESSION_LIMITS['depth']}",
        f"    const val EXPRESSION_NODES = {EXPRESSION_LIMITS['nodes']}",
    ]


def _kt_rules(props: dict[str, Any]) -> list[str]:
    lines = []
    for name, prop in sorted(props.items()):
        args = [
            kotlin_string(prop["type"]),
            f"required = {str(prop.get('required', False)).lower()}",
        ]
        # A family's constants are checked by its value parser, not by name.
        if "values" in prop and "valueType" not in prop:
            args.append(
                "values = setOf("
                + ", ".join(kotlin_string(value) for value in prop["values"])
                + ")"
            )
        if "since" in prop:
            args.append(f"since = {kotlin_string(prop['since'])}")
        if "valueType" in prop:
            args.append(f"valueType = {kotlin_string(prop['valueType'])}")
        if prop.get("nullable"):
            args.append("nullable = true")
        args.extend(
            f"{field} = {float(prop[field])}"
            for field in ("minimum", "maximum")
            if field in prop
        )
        lines.append(
            f"                {kotlin_string(name)} to PropertyRule({', '.join(args)}),"
        )
    return lines


def render_kotlin_registry(registry: dict[str, Any]) -> str:
    """Generate validation registrations from the same registry as Python."""
    minimum_schema = min(supported(registry), key=version_key)
    lines = [
        f"// {GENERATED_NOTICE}",
        "package com.pycompose.ir.generated",
        "",
        "import com.pycompose.ir.ComponentRule",
        "import com.pycompose.ir.PropertyRule",
        "",
        "object IrContract {",
        "    const val SCHEMA_VERSION: String = "
        + kotlin_string(registry["schemaVersion"]),
        "    const val MIN_SCHEMA_VERSION: String = " + kotlin_string(minimum_schema),
        "    val supportedSchemaVersions: Set<String> = setOf("
        + ", ".join(kotlin_string(value) for value in supported(registry))
        + ")",
        "    const val MIN_LIBRARY_VERSION: String = "
        + kotlin_string(registry["minLibraryVersion"]),
        "    val actionIds: Set<String> = setOf("
        + ", ".join(kotlin_string(name) for name in sorted(registry["actions"]))
        + ")",
        "    val components: Map<String, ComponentRule> = mapOf(",
    ]
    for name, spec in sorted(registry["components"].items()):
        lines.extend(
            [
                f"        {kotlin_string(name)} to ComponentRule(",
                "            slots = setOf("
                + ", ".join(
                    kotlin_string(slot) for slot in sorted(spec.get("slots", {}))
                )
                + "),",
                "            childrenAllowed = "
                + str(spec["children"]["allowed"]).lower()
                + ",",
                f"            minimumChildren = {spec['children'].get('min', 0)},",
                "            since = "
                + kotlin_string(spec.get("since", minimum_schema))
                + ",",
                "            props = mapOf(",
                *_kt_rules(spec["props"]),
                "            ),",
                "        ),",
            ]
        )
    lines.extend(
        ["    )", "    val modifiers: Map<String, Map<String, PropertyRule>> = mapOf("]
    )
    for name, spec in sorted(registry.get("modifiers", {}).items()):
        lines.extend(
            [
                f"        {kotlin_string(name)} to mapOf(",
                *_kt_rules(spec["props"]),
                "        ),",
            ]
        )
    lines.append("    )")
    lines.extend(_kt_streams(registry))
    lines.append(
        "    val actionPayloads: Map<String, Map<String, PropertyRule>> = mapOf("
    )
    for name, spec in sorted(registry["actions"].items()):
        lines.extend(
            [
                f"        {kotlin_string(name)} to mapOf(",
                *_kt_rules(spec["payload"]),
                "        ),",
            ]
        )
    lines.extend(
        [
            "    )",
            "    val effectPayloads: Map<String, Map<String, PropertyRule>> = mapOf(",
        ]
    )
    for name, spec in sorted(registry.get("effects", {}).items()):
        lines.extend(
            [
                f"        {kotlin_string(name)} to mapOf(",
                *_kt_rules(spec["payload"]),
                "        ),",
            ]
        )
    lines.extend(
        [
            "    )",
            "    val lifecyclePayloads: "
            "Map<String, Map<String, PropertyRule>> = mapOf(",
        ]
    )
    for name, spec in sorted(registry.get("lifecycle", {}).items()):
        lines.extend(
            [
                f"        {kotlin_string(name)} to mapOf(",
                *_kt_rules(spec["payload"]),
                "        ),",
            ]
        )
    return "\n".join([*lines, "    )", "}", ""])
