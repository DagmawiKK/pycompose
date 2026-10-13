package com.pycompose.renderer

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.jsonPrimitive

/** Fold ordered operations once. Any failed operation rejects the whole modifier. */
class ModifierBuilder(
    private val actions: ActionDispatcher,
) {
    private val operations: Map<String, (JsonObject) -> Modifier> =
        mapOf(
            "padding" to {
                Modifier.padding(PropResolver.dp(it.number("value")).getOrThrow())
            },
            "fillMaxWidth" to {
                val fraction = it.number("fraction")
                require(fraction.isFinite() && fraction in 0.0..1.0)
                Modifier.fillMaxWidth(fraction.toFloat())
            },
            "size" to {
                val width = PropResolver.dp(it.number("width")).getOrThrow()
                val height = PropResolver.dp(it.number("height")).getOrThrow()
                Modifier.size(width, height)
            },
            "clip" to {
                val shape = PropResolver.shape(it.string("shape")).getOrThrow()
                Modifier.clip(shape)
            },
            "clickable" to {
                val actionId = it.string("onClick")
                val enabled = checkNotNull(it["enabled"]?.jsonPrimitive?.booleanOrNull)
                Modifier.clickable(enabled = enabled) { actions.dispatch(actionId) }
            },
        )

    fun build(program: JsonObject?): Result<Modifier> =
        runCatching {
            if (program == null) return@runCatching Modifier
            val sequence =
                program["operations"] as? JsonArray
                    ?: error("Expected modifier operations")
            sequence.fold(Modifier as Modifier) { modifier, value ->
                val operation = value as? JsonObject ?: error("Expected modifier object")
                val type = operation.string("type")
                val resolve = checkNotNull(operations[type]) { "Unknown modifier: $type" }
                modifier.then(resolve(operation))
            }
        }

    private fun JsonObject.number(key: String): Double =
        checkNotNull(this[key]?.jsonPrimitive?.doubleOrNull)

    private fun JsonObject.string(key: String): String {
        val value = checkNotNull(this[key] as? JsonPrimitive)
        require(value.isString)
        return value.content
    }
}
