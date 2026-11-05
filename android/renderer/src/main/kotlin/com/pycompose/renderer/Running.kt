package com.pycompose.renderer

import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.MutableFloatState
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.unit.Density
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * A gesture's running totals in dp: what its continuous callback adds each frame -- a
 * drag's deltas -- kept for as long as its node is composed.
 */
class Running internal constructor(
    private val totals: List<MutableFloatState>,
) {
    /** Add one delta into the [index]-th total. */
    fun add(
        index: Int,
        delta: Float,
    ) {
        totals[index].floatValue += delta
    }
}

/**
 * The running totals of the gesture [node] wears, published under its id as the streams
 * [names] while it is composed, beside any its holder publishes.
 */
@Composable
fun rememberRunning(
    node: String,
    streams: MutableMap<String, Map<String, () -> Float>>,
    names: List<String>,
): Running {
    val totals = remember(node) { names.map { mutableFloatStateOf(0f) } }
    DisposableEffect(node, totals) {
        val own = names.zip(totals).associate { (name, total) -> name to { total.floatValue } }
        streams[node] = streams[node].orEmpty() + own
        onDispose {
            val left = streams[node].orEmpty() - names.toSet()
            if (left.isEmpty()) streams.remove(node) else streams[node] = left
        }
    }
    return remember(totals) { Running(totals) }
}

/** An event's position as its payload: `x` and `y` in dp. */
fun Density.offsetPayload(offset: Offset): JsonObject =
    JsonObject(
        mapOf(
            "x" to JsonPrimitive(offset.x.toDp().value),
            "y" to JsonPrimitive(offset.y.toDp().value),
        ),
    )
