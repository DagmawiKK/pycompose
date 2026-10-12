package com.pycompose.ir

import com.pycompose.ir.generated.IrContract
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.longOrNull

internal object WireValidator {
    fun validate(root: JsonObject) {
        require(root.keys.all { it in setOf("version", "schemaVersion", "root", "metadata") }) {
            "Unknown snapshot envelope field"
        }
        root["metadata"]?.let { require(it is JsonObject) { "metadata must be an object" } }
        val pending = ArrayDeque<JsonElement>()
        pending.addLast(checkNotNull(root["root"]) { "Missing root" })
        val ids = mutableSetOf<String>()
        while (pending.isNotEmpty()) {
            val node = pending.removeLast() as? JsonObject ?: error("Node must be an object")
            val id = string(node["id"], "node.id")
            require(id.isNotEmpty() && ids.add(id)) { "Empty or duplicate node id: $id" }
            val type = string(node["type"], "node.type")
            val spec = checkNotNull(IrContract.components[type]) { "Unknown component: $type" }
            require(node.keys.all { it in setOf("id", "type", "props", "children") }) {
                "Unknown node field at $id"
            }
            val props = node["props"] as? JsonObject ?: error("Missing object props at $id")
            properties(props, spec.props, "$id.props")
            require(spec.childrenAllowed || "children" !in node) { "Children forbidden at $id" }
            val children =
                node["children"]?.let {
                    it as? JsonArray ?: error("children must be an array at $id")
                } ?: JsonArray(emptyList())
            require(children.size >= spec.minimumChildren) { "Too few children at $id" }
            children.reversed().forEach(pending::addLast)
        }
    }

    fun string(
        value: JsonElement?,
        path: String,
    ): String {
        val primitive = value as? JsonPrimitive
        require(primitive != null && primitive.isString) { "$path must be a string" }
        return primitive.content
    }

    private fun properties(
        values: JsonObject,
        rules: Map<String, PropertyRule>,
        path: String,
    ) {
        rules.forEach { (name, rule) ->
            require(!rule.required || name in values) { "Missing required $path.$name" }
        }
        values.forEach { (name, value) ->
            val rule = checkNotNull(rules[name]) { "Unknown property $path.$name" }
            property(value, rule, "$path.$name")
        }
    }

    private fun property(
        value: JsonElement,
        rule: PropertyRule,
        path: String,
    ) {
        val primitive = value as? JsonPrimitive
        when (rule.type) {
            "string", "color" -> string(value, path)
            "enum" -> require(string(value, path) in rule.values) { "Invalid enum at $path" }
            "actionId" ->
                require(string(value, path) in IrContract.actionIds) {
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
            "number", "dp" -> {
                bounds(number(primitive, path), rule, path)
            }
            "modifier" -> modifier(value, path)
            else -> error("Unsupported registered prop type: ${rule.type}")
        }
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

    private fun modifier(
        value: JsonElement,
        path: String,
    ) {
        val objectValue = value as? JsonObject ?: error("$path must be a modifier object")
        val operations = objectValue["operations"] ?: return
        require(operations is JsonArray) { "$path.operations must be an array" }
        operations.forEachIndexed { index, item ->
            val operation =
                item as? JsonObject ?: error("Invalid modifier operation at $path[$index]")
            val type = string(operation["type"], "$path[$index].type")
            val rules = checkNotNull(IrContract.modifiers[type]) { "Unknown modifier: $type" }
            properties(JsonObject(operation.filterKeys { it != "type" }), rules, "$path[$index]")
        }
    }
}
