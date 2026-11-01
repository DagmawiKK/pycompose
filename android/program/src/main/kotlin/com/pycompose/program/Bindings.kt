package com.pycompose.program

import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.doubleOrNull

/** How a binding travels to its target; a renderer maps it onto its animation specs. */
sealed interface Travel {
    /** Read the target live: no travel of its own. */
    data object None : Travel

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

/** Where the host reads a bound value, and so what it invalidates. */
enum class Phase(
    val wire: String,
) {
    Composition("composition"),
    Layout("layout"),
    Draw("draw"),
    ;

    companion object {
        /** Read a phase, refusing any name outside the closed three. */
        fun read(name: String): Phase =
            entries.firstOrNull { it.wire == name }
                ?: error("A binding's phase is composition, layout or draw")
    }
}

/**
 * A value the host keeps at its target: the target as the wire states it, how to travel there,
 * and the phase it is read in.
 *
 * @property target The target, still in its wire form for the prop's own reader.
 * @property travel How it travels there, or [Travel.None] to read the target live.
 * @property phase Where the host reads it.
 */
data class Binding(
    val target: JsonElement,
    val travel: Travel,
    val phase: Phase,
)

/** Bindings' wire form, checked exactly as Python checks it. */
object Bindings {
    /** Whether a prop value is a binding's wire object. */
    fun isBinding(value: JsonElement?): Boolean =
        ((value as? JsonObject)?.get("type") as? JsonPrimitive)?.let {
            it.isString && it.content == "binding"
        } == true

    /**
     * Read a binding, refusing any other shape.
     *
     * @param value The `{"type": "binding", "target": ..., "travel": ..., "phase": ...}` object.
     * @return The target, its travel and the phase it is read in.
     */
    fun read(value: JsonObject): Binding {
        require(
            value.keys == setOf("type", "target", "travel", "phase"),
        ) { "A binding is {type: binding, target, travel, phase}" }
        val travel =
            travel(
                value["travel"] as? JsonObject ?: error("A binding's travel is an object"),
            )
        val phase =
            Phase.read(
                (value["phase"] as? JsonPrimitive)?.takeIf { it.isString }?.content
                    ?: error("A binding's phase is a string"),
            )
        return Binding(value.getValue("target"), travel, phase)
    }

    private fun travel(spec: JsonObject): Travel =
        when ((spec["kind"] as? JsonPrimitive)?.content) {
            "none" -> {
                require(spec.keys == setOf("kind")) { "Invalid none" }
                Travel.None
            }
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
            else -> error("A binding's travel is none, a spring or a tween")
        }

    private fun number(
        spec: JsonObject,
        name: String,
    ): Float {
        val primitive = spec[name] as? JsonPrimitive
        val number =
            primitive?.takeIf { !it.isString && it.booleanOrNull == null }?.doubleOrNull
        require(number != null && number.isFinite() && number >= 0) {
            "A binding's travel takes nonnegative numbers"
        }
        return number.toFloat()
    }
}
