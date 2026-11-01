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
import com.pycompose.program.Binding
import com.pycompose.program.Bindings
import com.pycompose.program.Phase
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
 * The binding a prop value carries, or null for a plain value.
 *
 * @param wire The prop's wire value: plain, or a binding.
 */
private fun bound(wire: JsonElement): Binding? {
    if (!Bindings.isBinding(wire)) return null
    val binding = Bindings.read(wire as JsonObject)
    // The generator resolved where this argument is read; a binding that names
    // another phase would be read in the wrong one, so it is refused instead.
    require(binding.phase == Phase.Composition) {
        "this prop is read in composition; a ${binding.phase.wire} binding cannot stand here"
    }
    return binding
}

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
    val binding = bound(wire) ?: return read(wire)
    return animateFloatAsState(read(binding.target), spec(binding.travel), label = "binding").value
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
    val binding = bound(wire) ?: return read(wire)
    return animateDpAsState(read(binding.target), spec(binding.travel), label = "binding").value
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
    val binding = bound(wire) ?: return read(wire)
    return animateColorAsState(read(binding.target), spec(binding.travel), label = "binding").value
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
        // A composition-phase follow collapses to its target; one that did not
        // would have been refused by bound().
        Travel.None -> error("a binding read in composition travels with a spring or a tween")
    }
