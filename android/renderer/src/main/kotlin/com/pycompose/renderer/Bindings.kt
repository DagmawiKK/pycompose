package com.pycompose.renderer

import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.AnimationSpec
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.animateDpAsState
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.Dp
import com.pycompose.program.Bindings
import com.pycompose.program.Travel
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject

/*
 * A binding is a target the app stated and a way to travel there. The host
 * animates with Compose's own animate*AsState: a later snapshot stating a new
 * target restarts the travel from wherever it is, and Python runs per target,
 * never per frame. A plain value is read as it stands.
 */

/**
 * A Float prop, animated when the app bound it.
 *
 * @param wire The prop's wire value: plain, or a binding.
 * @param read Reads a plain wire value.
 */
@Composable
fun animatedFloat(
    wire: JsonElement,
    read: @Composable (JsonElement) -> Float,
): Float {
    if (!Bindings.isBinding(wire)) return read(wire)
    val binding = Bindings.read(wire as JsonObject)
    return animateFloatAsState(read(binding.to), spec(binding.travel), label = "binding").value
}

/**
 * A Dp prop, animated when the app bound it.
 *
 * @param wire The prop's wire value: plain, or a binding.
 * @param read Reads a plain wire value.
 */
@Composable
fun animatedDp(
    wire: JsonElement,
    read: @Composable (JsonElement) -> Dp,
): Dp {
    if (!Bindings.isBinding(wire)) return read(wire)
    val binding = Bindings.read(wire as JsonObject)
    return animateDpAsState(read(binding.to), spec(binding.travel), label = "binding").value
}

/**
 * A colour prop, animated when the app bound it.
 *
 * @param wire The prop's wire value: plain, or a binding.
 * @param read Reads a plain wire value.
 */
@Composable
fun animatedColor(
    wire: JsonElement,
    read: @Composable (JsonElement) -> Color,
): Color {
    if (!Bindings.isBinding(wire)) return read(wire)
    val binding = Bindings.read(wire as JsonObject)
    return animateColorAsState(read(binding.to), spec(binding.travel), label = "binding").value
}

private fun <T> spec(travel: Travel): AnimationSpec<T> =
    when (travel) {
        is Travel.Spring -> spring(dampingRatio = travel.dampingRatio, stiffness = travel.stiffness)
        is Travel.Tween ->
            tween(
                durationMillis = travel.durationMs,
                delayMillis = travel.delayMs,
                easing = FastOutSlowInEasing,
            )
    }
