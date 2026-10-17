package com.pycompose.ir

import com.pycompose.ir.generated.ValueContract
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.longOrNull
import java.math.BigDecimal

/** Validate data before constructing any platform value. No Compose or Android imports. */
object ValueParser {
    private const val MAX_DEPTH = 64
    private const val FLOAT_MIN = 1.401298464324817e-45

    fun validate(
        value: JsonElement,
        family: String,
        specs: JsonObject = ValueContract.specs,
    ): Result<Unit> = runCatching { tagged(value, family, 0, specs) }

    internal fun validateFloat(value: JsonElement) {
        number(value, JsonObject(mapOf("type" to JsonPrimitive("float"))))
    }

    internal fun checkVersion(
        value: JsonElement,
        schema: String,
    ) {
        val pending = ArrayDeque<JsonElement>()
        pending.add(value)
        while (pending.isNotEmpty()) {
            when (val current = pending.removeLast()) {
                is JsonObject -> {
                    val name = (current["type"] as? JsonPrimitive)?.content
                    ValueContract.specs[name]?.jsonObject?.get("since")?.let {
                        require(VersionGate.available(schema, it.jsonPrimitive.content)) {
                            "Value requires newer schema"
                        }
                    }
                    pending.addAll(current.values)
                }
                is JsonArray -> pending.addAll(current)
                else -> Unit
            }
        }
    }

    private fun tagged(
        value: JsonElement,
        family: String,
        depth: Int,
        specs: JsonObject,
    ) {
        require(depth < MAX_DEPTH) { "Value nesting is too deep" }
        val data = value as? JsonObject ?: error("Value must be a tagged object")
        val name = WireValidator.string(data["type"], "value.type")
        val spec = specs[name]?.jsonObject ?: error("Unknown value constructor")
        require(spec["family"]?.jsonPrimitive?.content == family) { "Wrong value family" }
        val parameters = checkNotNull(spec["parameters"]).jsonObject
        require(data.keys.all { it == "type" || it in parameters }) { "Unknown value field" }
        parameters.forEach { (key, item) ->
            val rule = item.jsonObject
            val supplied = data[key]
            if (supplied == null) {
                require(rule["required"]?.jsonPrimitive?.booleanOrNull != true) {
                    "Missing value field: $key"
                }
            } else {
                parameter(supplied, rule, depth + 1, specs)
            }
        }
        spec["orderedParameters"]?.let { ordering ->
            val ordered = (ordering as JsonArray).map { it.jsonPrimitive.content }
            ordered.zipWithNext().forEach { (left, right) ->
                require(
                    checkNotNull(data.getValue(left).jsonPrimitive.doubleOrNull) <=
                        checkNotNull(data.getValue(right).jsonPrimitive.doubleOrNull),
                ) { "Value parameters must be ordered" }
            }
        }
    }

    private fun parameter(
        value: JsonElement,
        rule: JsonObject,
        depth: Int,
        specs: JsonObject,
    ) {
        if (value == JsonNull) {
            require(rule["nullable"]?.jsonPrimitive?.booleanOrNull == true) {
                "Value field is not nullable"
            }
            return
        }
        when (rule["type"]?.jsonPrimitive?.content) {
            "value" -> {
                tagged(value, checkNotNull(rule["valueType"]).jsonPrimitive.content, depth, specs)
                bounds(
                    value,
                    rule["minimum"]?.jsonPrimitive?.doubleOrNull,
                    rule["maximum"]?.jsonPrimitive?.doubleOrNull,
                )
            }
            "list" -> {
                val items = value as? JsonArray ?: error("Expected value list")
                val minimum = rule["minItems"]?.jsonPrimitive?.longOrNull ?: 0
                require(items.size >= minimum) { "Too few value items" }
                items.forEach {
                    parameter(
                        it,
                        checkNotNull(rule["items"]).jsonObject,
                        depth,
                        specs,
                    )
                }
            }
            "string" -> {
                val text = WireValidator.string(value, "value field")
                rule["values"]?.let { choices ->
                    require((choices as JsonArray).any { it.jsonPrimitive.content == text }) {
                        "Unknown native constant"
                    }
                }
            }
            "boolean" ->
                require(
                    value is JsonPrimitive && !value.isString && value.booleanOrNull != null,
                ) { "Expected boolean" }
            else -> number(value, rule)
        }
    }

    private fun number(
        value: JsonElement,
        rule: JsonObject,
    ) {
        val kind = checkNotNull(rule["type"]).jsonPrimitive.content
        val primitive = value as? JsonPrimitive ?: error("Expected native number")
        require(!primitive.isString) { "Expected numeric value" }
        val number = checkNotNull(primitive.doubleOrNull) { "Expected native number" }
        require(number.isFinite()) { "Native number must be finite" }
        // Canonical integers retain arbitrary precision; decimal/exponent tokens
        // denote the Python/JSON binary Double value before conversion to Float.
        val exact =
            if (primitive.content.any { it == '.' || it == 'e' || it == 'E' }) {
                BigDecimal(number)
            } else {
                primitive.content.toBigDecimal()
            }
        when (kind) {
            "int", "long" -> {
                val integer = checkNotNull(primitive.longOrNull) { "Native integer overflow" }
                require(kind == "long" || integer in Int.MIN_VALUE..Int.MAX_VALUE) {
                    "Native Int overflow"
                }
            }
            "float" -> {
                require(exact.abs() <= BigDecimal(Float.MAX_VALUE.toDouble())) {
                    "Native Float overflow"
                }
                require(exact.signum() == 0 || exact.abs() >= BigDecimal(FLOAT_MIN)) {
                    "Native Float underflow"
                }
            }
            "double" ->
                require(
                    exact.abs() <= BigDecimal(Double.MAX_VALUE),
                ) { "Native Double overflow" }
            else -> error("Unknown native scalar")
        }
        rule["minimum"]?.let { require(number >= checkNotNull(it.jsonPrimitive.doubleOrNull)) }
        rule["maximum"]?.let { require(number <= checkNotNull(it.jsonPrimitive.doubleOrNull)) }
    }

    internal fun bounds(
        value: JsonElement,
        minimum: Double?,
        maximum: Double?,
    ) {
        val scalar =
            ((value as? JsonObject)?.get("value") as? JsonPrimitive)?.doubleOrNull ?: return
        require(minimum == null || scalar >= minimum) { "Value below minimum" }
        require(maximum == null || scalar <= maximum) { "Value above maximum" }
    }
}
