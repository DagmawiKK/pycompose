package com.pycompose.host.ui

import androidx.compose.animation.core.VectorConverter
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.colorspace.ColorSpaces
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.pycompose.program.Phase
import com.pycompose.renderer.RenderContext
import com.pycompose.renderer.bindingState
import com.pycompose.renderer.expressionColor
import com.pycompose.renderer.generated.ValueResolver
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.double
import kotlinx.serialization.json.jsonPrimitive
import androidx.compose.animation.VectorConverter as colorVectorConverter

/*
 * A hand-written adapter reads its props while composing, so a prop the app may
 * bind is read through one state here, exactly as a generated adapter reads it.
 * The phase is composition: the native call takes the value, not a block.
 */

private val srgbColourConverter = Color.colorVectorConverter(ColorSpaces.Srgb)

/**
 * A dp prop the app may bind, or the default the native component declares.
 *
 * @param wire The prop's wire value, when stated.
 * @param fallback What the component uses when the prop is omitted.
 * @return The elevation or size the native call reads.
 */
@Composable
internal fun dpProp(
    wire: JsonElement?,
    fallback: Dp,
): Dp {
    if (wire == null) return fallback
    val state =
        bindingState(wire, Dp.VectorConverter, Phase.Composition) { plain ->
            plain.jsonPrimitive.double.dp
        }
    return state.value
}

/**
 * A colour prop the app may bind: its tagged value, or an expression over streams.
 *
 * @param wire The prop's wire value, when stated.
 * @return The colour, or [Color.Unspecified] to keep the content colour in scope.
 */
@Composable
internal fun RenderContext.nativeColor(wire: JsonElement?): Color {
    if (wire == null) return Color.Unspecified
    val state =
        bindingState(wire, srgbColourConverter, Phase.Composition) { plain ->
            plainColor(plain)
        }
    return state.value
}

@Composable
private fun RenderContext.plainColor(plain: JsonElement): Color =
    when (plain) {
        is JsonObject ->
            expressionColor(plain)
                ?: ValueResolver.color(plain).getOrDefault(Color.Unspecified)
        else -> Color.Unspecified
    }
