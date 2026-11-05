package com.pycompose.program

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.doubleOrNull

/**
 * What the catalog lets an expression use: its limits, its operations and the streams a
 * holder may publish. The language knows none of them itself.
 *
 * @property depth How deeply an expression may nest.
 * @property nodes How many nodes one expression may hold.
 * @property operations The operations the catalog declares.
 * @property streamNames Every stream name any holder publishes.
 */
data class Contract(
    val depth: Int,
    val nodes: Int,
    val operations: Set<String>,
    val streamNames: Set<String>,
)

/**
 * An expression's wire form, judged exactly as Python's validator judges it.
 *
 * Closed and total: numbers from literals and holder streams, combined by `times`, `plus`,
 * `minus` and `clamp`, and made a colour by `alpha` or `mix`.
 */
object Expressions {
    private val color = Regex("#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{8})")

    /** Whether a prop value is an expression's wire object. */
    fun isExpression(value: JsonElement?): Boolean =
        ((value as? JsonObject)?.get("type") as? JsonPrimitive)?.let {
            it.isString && it.content == "expression"
        } == true

    /**
     * The expression kind a prop type holds, or null when it holds none.
     *
     * A colour prop takes a colour expression; a dp or number prop takes a number expression. An
     * integer is not among them: an expression is evaluated in floating point every frame, and a
     * discrete value (an index, a line count) cannot follow one.
     *
     * @param type The prop's catalog type.
     */
    fun kindOf(type: String?): String? =
        when (type) {
            "color" -> "color"
            "dp", "number" -> "number"
            else -> null
        }

    /**
     * Check one expression and name the streams it reads.
     *
     * @param value The `{"type": "expression", "node": ...}` object.
     * @param expected The kind the prop needs: `number` or `color`.
     * @param contract The catalog's limits and vocabulary.
     * @return Each stream read, as (holder node id, stream name).
     */
    fun validate(
        value: JsonObject,
        expected: String,
        contract: Contract,
    ): List<Pair<String, String>> {
        require(value.keys == setOf("type", "node")) { "An expression is {type: expression, node}" }
        val streams = mutableListOf<Pair<String, String>>()
        val kind = Walk(streams, contract).kind(value.getValue("node"), 1)
        require(kind == expected) { "Expression gives a $kind, the prop needs a $expected" }
        return streams
    }

    /**
     * Every stream an expression in the snapshot reads names a node whose holder exposes it.
     *
     * A binding is read through its target, and a modifier's arguments are read too: an
     * expression is a fact about the value a prop or argument holds, not about where it is
     * written.
     *
     * @param root The snapshot's root node, already validated node by node.
     * @param contract The catalog's limits and vocabulary.
     * @param propKind The expression kind a component prop holds, or null when it holds none.
     * @param modifierKind The expression kind a modifier argument holds, or null for none.
     * @param published The streams a component type's holder publishes.
     */
    fun targets(
        root: JsonObject,
        contract: Contract,
        propKind: (type: String, prop: String) -> String?,
        modifierKind: (modifier: String, argument: String) -> String?,
        published: (JsonObject) -> Set<String>,
    ) {
        val nodes = mutableMapOf<String, JsonObject>()
        val reads = mutableListOf<Pair<String, String>>()
        val pending = ArrayDeque(listOf(root))
        while (pending.isNotEmpty()) {
            val node = pending.removeLast()
            val type = (node.getValue("type") as JsonPrimitive).content
            nodes[(node.getValue("id") as JsonPrimitive).content] = node
            (node["props"] as? JsonObject)?.forEach { (name, value) ->
                reads +=
                    if (name == "modifier") {
                        modifierReads(value, contract, modifierKind)
                    } else {
                        expressionReads(value, contract) { propKind(type, name) }
                    }
            }
            (node["children"] as? JsonArray)?.forEach { pending.add(it as JsonObject) }
        }
        reads.forEach { (holder, stream) ->
            require(stream in nodes[holder]?.let(published).orEmpty()) {
                "Stream $stream names no holder exposing it"
            }
        }
    }

    /** The streams one value's expression reads, a binding read through its target. */
    private fun expressionReads(
        value: JsonElement,
        contract: Contract,
        kind: () -> String?,
    ): List<Pair<String, String>> {
        val expression = expressionIn(value) ?: return emptyList()
        val expected = requireNotNull(kind()) { "This value cannot hold an expression" }
        return validate(expression, expected, contract)
    }

    /** The streams every expression a modifier's arguments carry read. */
    private fun modifierReads(
        value: JsonElement,
        contract: Contract,
        kind: (modifier: String, argument: String) -> String?,
    ): List<Pair<String, String>> {
        val operations = (value as? JsonObject)?.get("operations") as? JsonArray
        return operations.orEmpty().flatMap { operation ->
            val args = operation as? JsonObject ?: return@flatMap emptyList()
            val name = (args["type"] as? JsonPrimitive)?.content ?: return@flatMap emptyList()
            args.filterKeys { it != "type" }.flatMap { (argument, argumentValue) ->
                expressionReads(argumentValue, contract) { kind(name, argument) }
            }
        }
    }

    /** The expression a value states, or the target of a binding that states one. */
    private fun expressionIn(value: JsonElement): JsonObject? {
        val objectValue = value as? JsonObject ?: return null
        val stated =
            if (Bindings.isBinding(objectValue)) {
                Bindings.read(objectValue).target
            } else {
                objectValue
            }
        return if (isExpression(stated)) stated as JsonObject else null
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
        value != null &&
            !value.isString &&
            value.booleanOrNull == null &&
            value.doubleOrNull != null

    private class Walk(
        val streams: MutableList<Pair<String, String>>,
        val contract: Contract,
    ) {
        var count = 0

        fun kind(
            node: JsonElement,
            depth: Int,
        ): String {
            count += 1
            require(depth <= contract.depth && count <= contract.nodes) {
                "Expression exceeds its limits"
            }
            require(node is JsonObject) { "An expression node is an object" }
            return when {
                node.keys == setOf("number") && isNumber(node["number"] as? JsonPrimitive) ->
                    "number"
                node.keys == setOf("stream", "name") -> stream(node)
                else -> operation(node, depth)
            }
        }

        private fun stream(node: JsonObject): String {
            val holder = node["stream"] as? JsonPrimitive
            val name = (node["name"] as? JsonPrimitive)?.content
            require(holder != null && holder.isString && name in contract.streamNames) {
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
            require(op in contract.operations && shape != null && args != null) {
                "Unknown expression op $op"
            }
            require(
                args.size == shape.arity &&
                    node.keys == setOf("op", "args") + setOfNotNull(shape.colors),
            ) {
                "Expression op $op takes ${shape.arity} arguments"
            }
            require(args.all { kind(it, depth + 1) == "number" }) {
                "Expression op $op takes numbers"
            }
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
                        color.matches(
                            it.content,
                        )
                },
            ) {
                "Expression colours are #RRGGBB or #AARRGGBB"
            }
            return "color"
        }
    }
}
