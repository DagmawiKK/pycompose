package com.pycompose.ir

import com.pycompose.ir.generated.IrContract
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.doubleOrNull

/**
 * An expression's wire form, judged exactly as `pycompose/core/expressions.py` judges it.
 *
 * Closed and total (plan 31 §6): numbers from literals and holder streams,
 * combined by `times`, `plus`, `minus` and `clamp`, and made a colour by `alpha`
 * or `mix`. The vocabulary, the stream names and the limits are the generated
 * contract's, so the two validators cannot drift.
 */
object Expressions {
    private val color = Regex("#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{8})")

    /** Whether a prop value is an expression's wire object. */
    fun isExpression(value: JsonElement?): Boolean =
        ((value as? JsonObject)?.get("type") as? JsonPrimitive)?.let {
            it.isString && it.content == "expression"
        } == true

    /**
     * Check one expression and name the streams it reads.
     *
     * @param value The `{"type": "expression", "node": ...}` object.
     * @param expected The kind the prop needs: `number` or `color`.
     * @return Each stream read, as (holder node id, stream name).
     */
    fun validate(
        value: JsonObject,
        expected: String,
    ): List<Pair<String, String>> {
        require(value.keys == setOf("type", "node")) { "An expression is {type: expression, node}" }
        val streams = mutableListOf<Pair<String, String>>()
        val kind = Walk(streams).kind(value.getValue("node"), 1)
        require(kind == expected) { "Expression gives a $kind, the prop needs a $expected" }
        return streams
    }

    /**
     * Every stream an expression in the snapshot reads names a node whose holder exposes it.
     *
     * @param root The snapshot's root node, already validated node by node.
     */
    fun targets(root: JsonObject) {
        val types = mutableMapOf<String, String>()
        val reads = mutableListOf<Pair<String, String>>()
        val pending = ArrayDeque(listOf(root))
        while (pending.isNotEmpty()) {
            val node = pending.removeLast()
            types[(node.getValue("id") as JsonPrimitive).content] =
                (node.getValue("type") as JsonPrimitive).content
            (node["props"] as? JsonObject)?.values?.filter(::isExpression)?.forEach {
                reads += validate(it as JsonObject, "color")
            }
            (node["children"] as? JsonArray)?.forEach { pending.add(it as JsonObject) }
        }
        reads.forEach { (holder, stream) ->
            require(stream in IrContract.streams[types[holder]].orEmpty()) {
                "Stream $stream names no holder exposing it"
            }
        }
    }

    /** One op's shape: how many number arguments, and the colour field it carries. */
    private class Shape(
        val arity: Int,
        val colors: String? = null,
    )

    private val shapes =
        mapOf(
            "times" to Shape(arity = 2),
            "plus" to Shape(arity = 2),
            "minus" to Shape(arity = 2),
            "clamp" to Shape(arity = 3),
            "alpha" to Shape(arity = 1, colors = "color"),
            "mix" to Shape(arity = 1, colors = "colors"),
        )

    private fun isNumber(value: JsonPrimitive?): Boolean =
        value != null && !value.isString && value.booleanOrNull == null &&
            value.doubleOrNull != null

    private class Walk(
        val streams: MutableList<Pair<String, String>>,
    ) {
        var count = 0

        fun kind(
            node: JsonElement,
            depth: Int,
        ): String {
            count += 1
            require(depth <= IrContract.EXPRESSION_DEPTH && count <= IrContract.EXPRESSION_NODES) {
                "Expression exceeds its limits"
            }
            require(node is JsonObject) { "An expression node is an object" }
            return when {
                node.keys ==
                    setOf(
                        "number",
                    ) && isNumber(node["number"] as? JsonPrimitive) -> "number"
                node.keys == setOf("stream", "name") -> stream(node)
                else -> operation(node, depth)
            }
        }

        private fun stream(node: JsonObject): String {
            val holder = node["stream"] as? JsonPrimitive
            val name = (node["name"] as? JsonPrimitive)?.content
            require(holder != null && holder.isString && name in IrContract.streamNames) {
                "Unknown stream $name"
            }
            streams += holder.content to checkNotNull(name)
            return "number"
        }

        private fun operation(
            node: JsonObject,
            depth: Int,
        ): String {
            val op = (node["op"] as? JsonPrimitive)?.content
            val args = node["args"] as? JsonArray
            val shape = shapes[op]
            require(op in IrContract.expressionOps && shape != null && args != null) {
                "Unknown expression op $op"
            }
            require(
                args.size == shape.arity &&
                    node.keys == setOf("op", "args") + setOfNotNull(shape.colors),
            ) {
                "Expression op $op takes ${shape.arity} arguments"
            }
            require(
                args.all { kind(it, depth + 1) == "number" },
            ) { "Expression op $op takes numbers" }
            val colors =
                when (val field = shape.colors?.let(node::getValue)) {
                    null -> return "number"
                    is JsonArray -> field.toList()
                    else -> listOf(field)
                }
            require(op != "mix" || colors.size == 2) { "mix takes two colours" }
            require(
                colors.all {
                    (it as? JsonPrimitive)?.isString == true &&
                        color.matches(it.content)
                },
            ) {
                "Expression colours are #RRGGBB or #AARRGGBB"
            }
            return "color"
        }
    }
}
