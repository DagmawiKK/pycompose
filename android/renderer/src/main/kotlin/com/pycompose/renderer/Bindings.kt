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
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.structuralEqualityPolicy
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.pycompose.program.Binding
import com.pycompose.program.Bindings
import com.pycompose.program.Phase
import com.pycompose.program.Travel
import com.pycompose.renderer.generated.ValueResolver
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

/**
 * A prop a component reads while composing: plain, read as it stands with no state kept for it,
 * or bound, travelling through [converter].
 *
 * @param wire The prop's wire value: plain, or a binding.
 * @param converter The pin's converter for the prop's type.
 * @param read Reads a plain wire value.
 * @return The value to pass this composition.
 */
@Composable
fun <T, V : AnimationVector> bound(
    wire: JsonElement,
    converter: TwoWayConverter<T, V>,
    read: @Composable (JsonElement) -> T,
): T {
    val binding = bound(wire)?.at(Phase.Composition) ?: return read(wire)
    return animateValueAsState(
        read(binding.target),
        converter,
        spec(binding.travel),
        label = "binding",
    ).value
}

/**
 * A colour prop read while composing, or [fallback] when it was omitted or names no colour.
 *
 * @param wire The prop's wire value, or null when omitted.
 * @param converter The pin's converter for colours.
 * @param fallback What the component uses when the app states nothing.
 * @return The colour to pass this composition.
 */
@Composable
fun <V : AnimationVector> RenderContext.boundColor(
    wire: JsonElement?,
    converter: TwoWayConverter<Color, V>,
    fallback: Color,
): Color {
    if (wire == null) return fallback
    return bound(wire, converter) { plain ->
        (plain as? JsonObject)?.let {
            expressionColor(it)
                ?: ValueResolver.color(it).getOrDefault(fallback)
        }
            ?: fallback
    }
}

/**
 * A dp prop read while composing, or [fallback] when it was omitted.
 *
 * @param wire The prop's wire value, or null when omitted.
 * @param converter The pin's converter for dp.
 * @param fallback What the component uses when the app states nothing.
 * @return The dp to pass this composition.
 */
@Composable
fun <V : AnimationVector> RenderContext.boundDp(
    wire: JsonElement?,
    converter: TwoWayConverter<Dp, V>,
    fallback: Dp,
): Dp = if (wire == null) fallback else bound(wire, converter) { number(it).dp }

/**
 * A prop a block Compose invokes later reads -- while laying out or drawing -- whose reader
 * needs no composition, as a number's or a dp's does.
 *
 * A live value -- an expression over holder streams, or a follow of one -- is read inside a
 * derived state the block reads, so a moving stream invalidates that phase alone and never
 * the composition. A value that travels animates as any binding does.
 *
 * @param wire The prop's wire value: plain, a binding, or null when omitted.
 * @param converter The pin's converter for the prop's type.
 * @param phase Where the block reads the value.
 * @param read Reads a plain wire value; it may read holder streams, never composition.
 * @return The value's state, or null when the prop was omitted.
 */
@Composable
fun <T, V : AnimationVector> deferredState(
    wire: JsonElement?,
    converter: TwoWayConverter<T, V>,
    phase: Phase,
    read: (JsonElement) -> T,
): State<T>? {
    if (wire == null) return null
    val binding = bound(wire)?.at(phase)
    return if (binding == null || binding.travel == Travel.None) {
        val current = rememberUpdatedState(binding?.target ?: wire)
        // The latest reader, so what it captured in composition (a colour scheme) stays
        // current; a new reader giving the same value invalidates nothing.
        val reader = rememberUpdatedState(read)
        remember { derivedStateOf(structuralEqualityPolicy()) { reader.value(current.value) } }
    } else {
        animateValueAsState(
            read(binding.target),
            converter,
            spec(binding.travel),
            label = "binding",
        )
    }
}

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
