package com.pycompose.renderer

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import com.pycompose.ir.IrParser
import com.pycompose.renderer.generated.ValueResolver
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
    private val operations: Map<String, @Composable (JsonObject) -> Modifier> =
        mapOf(
            "padding" to {
                val value = it["value"]
                if (value is JsonObject) {
                    Modifier.padding(ValueResolver.paddingValues(value).getOrThrow())
                } else {
                    Modifier.padding(PropResolver.dp(it.number("value")).getOrThrow())
                }
            },
            "fillMaxWidth" to {
                val fraction = it.number("fraction")
                require(fraction.isFinite() && fraction in 0.0..1.0)
                Modifier.fillMaxWidth(fraction.toFloat())
            },
            "size" to {
                val width = it.dimension("width")
                val height = it.dimension("height")
                Modifier.size(width, height)
            },
            "clip" to {
                val value = it["shape"]
                val shape =
                    if (value is JsonObject) {
                        ValueResolver
                            .shape(
                                value,
                            ).getOrThrow()
                    } else {
                        PropResolver.shape(it.string("shape")).getOrThrow()
                    }
                Modifier.clip(shape)
            },
            "clickable" to {
                val actionId = it.string("onClick")
                val enabled = checkNotNull(it["enabled"]?.jsonPrimitive?.booleanOrNull)
                Modifier.clickable(enabled = enabled) { actions.dispatch(actionId) }
            },
            "background" to
                { Modifier.background(ValueResolver.brush(it.getValue("brush")).getOrThrow()) },
            "windowInsetsPadding" to
                {
                    Modifier.windowInsetsPadding(
                        ValueResolver.windowInsets(it.getValue("insets")).getOrThrow(),
                    )
                },
        )

    @Composable
    fun build(program: JsonObject?): Result<Modifier> {
        if (program == null) return Result.success(Modifier)
        val prepared =
            runCatching {
                val sequence =
                    program["operations"] as? JsonArray
                        ?: error("Expected modifier operations")
                val ids =
                    sequence
                        .mapNotNull {
                            (it as? JsonObject)?.get("onClick") as? JsonPrimitive
                        }.map { it.content }
                        .toSet()
                IrParser.validateModifier(program, ids).getOrThrow()
                sequence.map { it as JsonObject }
            }
        return prepared.fold(
            onSuccess = { sequence ->
                val modifier =
                    sequence.fold(Modifier as Modifier) { modifier, operation ->
                        modifier.then(operations.getValue(operation.string("type"))(operation))
                    }
                Result.success(modifier)
            },
            onFailure = { Result.failure(it) },
        )
    }

    private fun JsonObject.number(key: String): Double =
        checkNotNull(this[key]?.jsonPrimitive?.doubleOrNull)

    @Composable
    private fun JsonObject.dimension(key: String): androidx.compose.ui.unit.Dp {
        val value = getValue(key)
        val dimension =
            if (value is JsonObject) {
                ValueResolver
                    .dp(
                        value,
                    ).getOrThrow()
            } else {
                PropResolver.dp(number(key)).getOrThrow()
            }
        require(dimension.value >= 0f)
        return dimension
    }

    private fun JsonObject.string(key: String): String {
        val value = checkNotNull(this[key] as? JsonPrimitive)
        require(value.isString)
        return value.content
    }
}
