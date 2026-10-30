package com.pycompose.program

import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.doubleOrNull

/** How a binding travels to its target; a renderer maps it onto its animation specs. */
sealed interface Travel {
    /** A physical spring: 1 settles without bouncing, below 1 bounces. */
    data class Spring(
        val dampingRatio: Float,
        val stiffness: Float,
    ) : Travel

    /** A timed curve with the standard easing. */
    data class Tween(
        val durationMs: Int,
        val delayMs: Int,
    ) : Travel
}

/**
 * A value the host animates to: the target as the wire states it, and how to travel there.
 *
 * @property to The target, still in its wire form for the prop's own reader.
 * @property travel The animation spec.
 */
data class Binding(
    val to: JsonElement,
    val travel: Travel,
)

/** Bindings' wire form, checked exactly as Python checks it. */
object Bindings {
    /** Whether a prop value is a binding's wire object. */
    fun isBinding(value: JsonElement?): Boolean =
        ((value as? JsonObject)?.get("type") as? JsonPrimitive)?.let {
            it.isString && it.content == "animate"
        } == true

    /**
     * Read a binding, refusing any other shape.
     *
     * @param value The `{"type": "animate", "to": ..., "spec": ...}` object.
     * @return The target and its travel.
     */
    fun read(value: JsonObject): Binding {
        require(
            value.keys == setOf("type", "to", "spec"),
        ) { "A binding is {type: animate, to, spec}" }
        val spec = value["spec"] as? JsonObject ?: error("A binding's spec is an object")
        val travel =
            when ((spec["kind"] as? JsonPrimitive)?.content) {
                "spring" -> {
                    require(
                        spec.keys == setOf("kind", "dampingRatio", "stiffness"),
                    ) { "Invalid spring" }
                    Travel.Spring(number(spec, "dampingRatio"), number(spec, "stiffness"))
                }
                "tween" -> {
                    require(spec.keys == setOf("kind", "durationMs", "delayMs")) { "Invalid tween" }
                    Travel.Tween(
                        number(spec, "durationMs").toInt(),
                        number(spec, "delayMs").toInt(),
                    )
                }
                else -> error("A binding's spec is a spring or a tween")
            }
        return Binding(value.getValue("to"), travel)
    }

    private fun number(
        spec: JsonObject,
        name: String,
    ): Float {
        val primitive = spec[name] as? JsonPrimitive
        val number =
            primitive?.takeIf { !it.isString && it.booleanOrNull == null }?.doubleOrNull
        require(number != null && number.isFinite() && number >= 0) {
            "A binding's spec takes nonnegative numbers"
        }
        return number.toFloat()
    }
}
