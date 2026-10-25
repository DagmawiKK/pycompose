package com.pycompose.ir

import com.pycompose.ir.generated.IrContract
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.longOrNull

/**
 * Subtrees validated last pass, valid while the schema and the action ids are unchanged.
 *
 * A subtree's validity depends only on itself, the schema version and which
 * action ids exist, so a recurring subtree is not checked again; its ids are
 * still claimed, so a duplicate against a changed node is still found.
 */
internal class ValidationCache {
    private var key: Pair<String, Set<String>>? = null
    private var memo = IdentityMemo<List<String>>()

    fun reset() {
        key = null
    }

    fun memoFor(
        schema: String,
        actionIds: Set<String>,
    ): IdentityMemo<List<String>> {
        if (key != schema to actionIds) {
            key = schema to actionIds
            memo = IdentityMemo()
        }
        memo.start()
        return memo
    }
}

internal object WireValidator {
    fun validate(
        root: JsonObject,
        cache: ValidationCache? = null,
    ) {
        require(root.keys.all { it in setOf("version", "schemaVersion", "root", "metadata") }) {
            "Unknown snapshot envelope field"
        }
        root["metadata"]?.let { require(it is JsonObject) { "metadata must be an object" } }
        val schema = string(root["schemaVersion"], "schemaVersion")
        val metadata = root["metadata"] as? JsonObject
        Effects.read(metadata, schema)
        AppData.read(metadata, schema)
        Echoes.read(metadata)
        val bindings = AppBindings.read(metadata, schema)
        val actionIds = IrContract.actionIds + bindings.keys
        val rootNode =
            checkNotNull(root["root"]) { "Missing root" } as? JsonObject
                ?: error("root must be an object")
        require("slot" !in rootNode) { "The root cannot fill a slot" }
        NodeWalk(schema, actionIds, cache?.memoFor(schema, actionIds)).run(rootNode)
        Expressions.targets(rootNode)
    }

    /**
     * Children of one node, after checking that each may compose where it says.
     *
     * A child either fills a slot its parent declared or is a primary child --
     * the only reading under which `minimumChildren` means anything, since a
     * `topBar` is no part of a component's content.
     */
    internal fun validatedChildren(
        node: JsonObject,
        spec: ComponentRule,
        id: String,
    ): JsonArray {
        val children =
            node["children"]?.let {
                it as? JsonArray ?: error("children must be an array at $id")
            } ?: JsonArray(emptyList())
        var primary = 0
        children.forEach { child ->
            val slot = (child as? JsonObject)?.get("slot")?.let { string(it, "$id.slot") }
            if (slot == null) {
                require(spec.childrenAllowed) { "Children forbidden at $id" }
                primary += 1
            } else {
                require(slot in spec.slots) { "Unknown slot $slot at $id" }
            }
        }
        require(primary >= spec.minimumChildren) { "Too few children at $id" }
        return children
    }

    fun string(
        value: JsonElement?,
        path: String,
    ): String {
        val primitive = value as? JsonPrimitive
        require(primitive != null && primitive.isString) { "$path must be a string" }
        return primitive.content
    }

    internal fun properties(
        values: JsonObject,
        rules: Map<String, PropertyRule>,
        path: String,
        actionIds: Set<String> = IrContract.actionIds,
        requireFields: Boolean = true,
    ) {
        rules.forEach { (name, rule) ->
            require(
                !requireFields || !rule.required || name in values,
            ) { "Missing required $path.$name" }
        }
        values.forEach { (name, value) ->
            val rule = checkNotNull(rules[name]) { "Unknown property $path.$name" }
            property(value, rule, "$path.$name", actionIds)
        }
    }

    private fun property(
        value: JsonElement,
        rule: PropertyRule,
        path: String,
        actionIds: Set<String>,
    ) {
        if (value == JsonNull && rule.nullable) return
        if (rule.valueType != null && value is JsonObject) {
            ValueParser.validate(value, rule.valueType).getOrThrow()
            ValueParser.bounds(value, rule.minimum, rule.maximum)
            return
        }
        if (rule.type == "value") {
            // A value prop is always its family's tagged object: a bare string
            // names no family, so there is nothing to resolve it against.
            error("$path must be its family's tagged value object")
        }
        legacyProperty(value, rule, path, actionIds)
    }

    private fun legacyProperty(
        value: JsonElement,
        rule: PropertyRule,
        path: String,
        actionIds: Set<String>,
    ) {
        val primitive = value as? JsonPrimitive
        when (rule.type) {
            "string", "color" -> string(value, path)
            "resource" -> ResourceReference.parse(string(value, path), rule.values).getOrThrow()
            "enum" -> require(string(value, path) in rule.values) { "Invalid enum at $path" }
            "actionId" ->
                require(string(value, path) in actionIds) {
                    "Undeclared action at $path"
                }
            "boolean" ->
                require(
                    primitive != null && !primitive.isString && primitive.booleanOrNull != null,
                ) {
                    "$path must be a boolean"
                }
            "integer", "durationMs" -> {
                require(primitive != null && !primitive.isString && primitive.longOrNull != null) {
                    "$path must be an integer"
                }
                bounds(checkNotNull(primitive.longOrNull).toDouble(), rule, path)
            }
            "number", "dp" -> numericProperty(value, rule, path)
            "modifier" -> modifier(value, path, actionIds)
            else -> error("Unsupported registered prop type: ${rule.type}")
        }
    }

    private fun numericProperty(
        value: JsonElement,
        rule: PropertyRule,
        path: String,
    ) {
        if (rule.type == "dp") ValueParser.validateFloat(value)
        bounds(number(value as? JsonPrimitive, path), rule, path)
    }

    private fun number(
        value: JsonPrimitive?,
        path: String,
    ): Double {
        val number = value?.doubleOrNull
        require(value != null && !value.isString && number != null && number.isFinite()) {
            "$path must be a finite number"
        }
        return number
    }

    private fun bounds(
        value: Double,
        rule: PropertyRule,
        path: String,
    ) {
        require(rule.minimum == null || value >= rule.minimum) { "$path below minimum" }
        require(rule.maximum == null || value <= rule.maximum) { "$path above maximum" }
    }

    internal fun modifier(
        value: JsonElement,
        path: String,
        actionIds: Set<String>,
    ) {
        val objectValue = value as? JsonObject ?: error("$path must be a modifier object")
        val operations = objectValue["operations"] ?: return
        require(operations is JsonArray) { "$path.operations must be an array" }
        operations.forEachIndexed { index, item ->
            val operation =
                item as? JsonObject ?: error("Invalid modifier operation at $path[$index]")
            val type = string(operation["type"], "$path[$index].type")
            val rules = checkNotNull(IrContract.modifiers[type]) { "Unknown modifier: $type" }
            properties(
                JsonObject(operation.filterKeys { it != "type" }),
                rules,
                "$path[$index]",
                actionIds,
            )
        }
    }
}

/** Every node, post-order, so a validated subtree knows every id it claims. */
private class NodeWalk(
    private val schema: String,
    private val actionIds: Set<String>,
    private val memo: IdentityMemo<List<String>>?,
) {
    private val ids = mutableSetOf<String>()
    private val claimed = ArrayDeque<MutableList<String>>()

    fun run(rootNode: JsonObject) {
        val pending = ArrayDeque<Pair<JsonObject, Boolean>>()
        pending.addLast(rootNode to true)
        while (pending.isNotEmpty()) {
            val (node, entering) = pending.removeLast()
            val reused = if (entering) memo?.get(node) else null
            when {
                !entering -> finish(node)
                reused != null -> claim(reused)
                else -> {
                    pending.addLast(node to false)
                    enter(node).reversed().forEach {
                        pending.addLast(
                            (it as? JsonObject ?: error("Node must be an object")) to true,
                        )
                    }
                }
            }
        }
    }

    private fun claim(reused: List<String>) {
        require(reused.all(ids::add)) { "Empty or duplicate node id in ${reused.first()}" }
        claimed.lastOrNull()?.addAll(reused)
    }

    private fun enter(node: JsonObject): JsonArray {
        val id = WireValidator.string(node["id"], "node.id")
        val type = WireValidator.string(node["type"], "node.type")
        val spec = checkNotNull(IrContract.components[type]) { "Unknown component: $type" }
        require(VersionGate.available(schema, spec.since)) { "Component requires newer schema" }
        require(node.keys.all { it in setOf("id", "type", "props", "slot", "children") }) {
            "Unknown node field at $id"
        }
        val props = node["props"] as? JsonObject ?: error("Missing object props at $id")
        ValueParser.checkVersion(props, schema)
        props.keys.forEach { key ->
            spec.props[key]?.let { rule ->
                require(VersionGate.available(schema, rule.since)) { "Prop requires newer schema" }
            }
        }
        WireValidator.properties(props, spec.props, "$id.props", actionIds)
        require(id.isNotEmpty() && ids.add(id)) { "Empty or duplicate node id: $id" }
        claimed.addLast(mutableListOf(id))
        return WireValidator.validatedChildren(node, spec, id)
    }

    private fun finish(node: JsonObject) {
        val own = claimed.removeLast()
        memo?.set(node, own)
        claimed.lastOrNull()?.addAll(own)
    }
}
