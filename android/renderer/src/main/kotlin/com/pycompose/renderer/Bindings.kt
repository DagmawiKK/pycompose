package com.pycompose.renderer

import androidx.compose.animation.core.AnimationSpec
import androidx.compose.animation.core.AnimationVector
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.TwoWayConverter
import androidx.compose.animation.core.animateValueAsState
import androidx.compose.animation.core.snap
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.runtime.Composable
import androidx.compose.runtime.State
import androidx.compose.runtime.rememberUpdatedState
import com.pycompose.program.Binding
import com.pycompose.program.Bindings
import com.pycompose.program.Phase
import com.pycompose.program.Travel
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject

/*
 * A binding is a target the app stated and a way to travel there. The host
 * animates with Compose's own animateValueAsState through the converter the pin
 * declares for the prop's type: a later snapshot stating a new target restarts
 * the travel from wherever it is, and Python runs per target, never per frame.
 * A plain value is read as it stands.
 */

/**
 * A prop's value, kept at its target when the app bound it.
 *
 * @param wire The prop's wire value: plain, or a binding.
 * @param converter The pin's converter for the prop's type.
 * @param phase Where this call site reads the value.
 * @param read Reads a plain wire value.
 * @return The value's state; a composition call site reads `.value`.
 */
@Composable
fun <T, V : AnimationVector> bindingState(
    wire: JsonElement,
    converter: TwoWayConverter<T, V>,
    phase: Phase = Phase.Composition,
    read: @Composable (JsonElement) -> T,
): State<T> {
    val binding = bound(wire)?.at(phase) ?: return rememberUpdatedState(read(wire))
    return animateValueAsState(
        read(binding.target),
        converter,
        spec(binding.travel),
        label = "binding",
    )
}

/**
 * A deferred prop's value, kept at its target, or null when the prop was omitted.
 *
 * A call site Compose invokes later -- while laying out or drawing -- declares
 * its states before the block and reads them inside it, so a frame of animation
 * invalidates that phase alone.
 *
 * @param wire The prop's wire value: plain, a binding, or null when omitted.
 * @param converter The pin's converter for the prop's type.
 * @param phase Where the block reads the value.
 * @param read Reads a plain wire value.
 * @return The value's state, or null when the prop was omitted.
 */
@Composable
fun <T, V : AnimationVector> optionalBindingState(
    wire: JsonElement?,
    converter: TwoWayConverter<T, V>,
    phase: Phase,
    read: @Composable (JsonElement) -> T,
): State<T>? = if (wire == null) null else bindingState(wire, converter, phase, read)

/** The binding a prop value carries, or null for a plain value. */
private fun bound(wire: JsonElement): Binding? {
    if (!Bindings.isBinding(wire)) return null
    return Bindings.read(wire as JsonObject)
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
        // A follow is read live: the target, held without travelling to it.
        Travel.None -> snap()
    }
