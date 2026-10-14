package com.pycompose.ir

import com.pycompose.ir.generated.IrContract
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * Host-initiated lifecycle events. These are declared separately from actions
 * because the host emits them unprompted: a component may not bind one to a tap.
 */
object Lifecycle {
    val ids: Set<String> = IrContract.lifecyclePayloads.keys

    fun check(
        event: String,
        payload: JsonObject,
    ) {
        val rules =
            checkNotNull(IrContract.lifecyclePayloads[event]) {
                "Undeclared lifecycle event: $event"
            }
        WireValidator.properties(payload, rules, "lifecycle.$event.payload")
    }

    fun payload(
        orientation: String,
        darkMode: Boolean,
        locale: String,
        density: Double,
    ): JsonObject =
        JsonObject(
            mapOf(
                "orientation" to JsonPrimitive(orientation),
                "darkMode" to JsonPrimitive(darkMode),
                "locale" to JsonPrimitive(locale),
                "density" to JsonPrimitive(density),
            ),
        )

    /** The destination a route change asks Python to render. */
    fun route(destination: String): JsonObject =
        JsonObject(mapOf("route" to JsonPrimitive(destination)))

    /** Orientation as Android reports it, mapped to the two values Python sees. */
    fun orientation(landscape: Boolean): String = if (landscape) "landscape" else "portrait"
}
