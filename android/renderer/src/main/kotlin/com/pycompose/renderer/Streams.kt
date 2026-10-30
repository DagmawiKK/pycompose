package com.pycompose.renderer

import androidx.compose.foundation.ScrollState
import androidx.compose.material3.DrawerState
import androidx.compose.material3.DrawerValue
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.lerp
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.doubleOrNull

/*
 * Streams and expressions: behaviour as data.
 *
 * A holder publishes the numbers it exposes -- a drawer's open fraction, a
 * scroll's offset and fraction -- under its node's id, read from its public
 * properties only. An expression the app bound to a colour prop reads them
 * during composition, so the reading adapter recomposes as they move and
 * Python never runs per frame. The wire form was checked by both validators
 * (`Expressions`); evaluation still degrades to the prop's fallback.
 */

/** One stream: the current value, read where an expression evaluates. */
internal typealias Stream = () -> Float

/**
 * Publish a holder's streams for as long as its node is composed.
 *
 * @param node The node's wire id, which expressions name.
 * @param holder The node's native state holder.
 */
@Composable
fun RenderContext.publish(
    node: String,
    holder: Any,
) {
    val streams =
        when (holder) {
            is DrawerState -> mapOf("progress" to holder.progress())
            is ScrollState ->
                mapOf(
                    "offset" to { holder.value.toFloat() },
                    "progress" to {
                        if (holder.maxValue > 0) holder.value.toFloat() / holder.maxValue else 0f
                    },
                )
            else -> return
        }
    DisposableEffect(node, holder) {
        renderer.streams[node] = streams
        onDispose { renderer.streams.remove(node) }
    }
}

/**
 * A drawer's open fraction: 0 closed, 1 open, following a drag in between.
 *
 * The sheet's offset is public, its travel is not; the offset at rest while
 * closed is that travel, so the fraction is measured against it. Before the
 * drawer has rested closed, the settled value stands in.
 */
@Composable
private fun DrawerState.progress(): Stream {
    val closed = remember(this) { mutableFloatStateOf(Float.NaN) }
    LaunchedEffect(this) {
        snapshotFlow { Triple(currentValue, isAnimationRunning, currentOffset) }
            .collect { (value, moving, offset) ->
                val resting = value == DrawerValue.Closed && !moving
                if (resting && offset.isFinite() && offset != 0f) closed.floatValue = offset
            }
    }
    return {
        val travel = closed.floatValue
        val offset = currentOffset
        if (travel.isNaN() || offset.isNaN()) {
            if (isOpen) 1f else 0f
        } else {
            (1f - offset / travel).coerceIn(0f, 1f)
        }
    }
}

/**
 * Evaluate an expression the app bound to a colour prop, or null for a colour value.
 *
 * @param wire The prop's tagged object.
 * @return The colour, or null when [wire] is not an expression or cannot evaluate.
 */
@Composable
fun RenderContext.expressionColor(wire: JsonObject): Color? {
    if ((wire["type"] as? JsonPrimitive)?.content != "expression") return null
    val streams = renderer.streams
    return runCatching { color(wire.getValue("node") as JsonObject, streams) }.getOrNull()
}

private fun color(
    node: JsonObject,
    streams: Map<String, Map<String, Stream>>,
): Color {
    val argument = (node.getValue("args") as JsonArray)[0] as JsonObject
    val fraction = number(argument, streams).coerceIn(0f, 1f)
    return when ((node["op"] as JsonPrimitive).content) {
        "alpha" -> {
            val color = hex((node.getValue("color") as JsonPrimitive).content)
            color.copy(alpha = color.alpha * fraction)
        }
        else -> {
            val colors =
                (
                    node.getValue(
                        "colors",
                    ) as JsonArray
                ).map { hex((it as JsonPrimitive).content) }
            lerp(colors[0], colors[1], fraction)
        }
    }
}

private fun number(
    node: JsonObject,
    streams: Map<String, Map<String, Stream>>,
): Float {
    val literal = (node["number"] as? JsonPrimitive)?.doubleOrNull
    val holder = (node["stream"] as? JsonPrimitive)?.content
    return when {
        literal != null -> literal.toFloat()
        // A holder not composed yet reads as at rest; its publish recomposes this.
        holder != null ->
            streams[holder]?.get((node.getValue("name") as JsonPrimitive).content)?.invoke() ?: 0f
        else -> operation(node, streams)
    }
}

private fun operation(
    node: JsonObject,
    streams: Map<String, Map<String, Stream>>,
): Float {
    val args = (node.getValue("args") as JsonArray).map { number(it as JsonObject, streams) }
    return when ((node["op"] as JsonPrimitive).content) {
        "times" -> args[0] * args[1]
        "plus" -> args[0] + args[1]
        "minus" -> args[0] - args[1]
        else -> args[0].coerceIn(args[1], args[2])
    }
}

/** `#RRGGBB` is opaque; `#AARRGGBB` carries its own alpha. */
private fun hex(value: String): Color {
    val digits = value.removePrefix("#")
    return Color(digits.padStart(OPAQUE.length, 'F').toLong(HEX).toInt())
}

private const val OPAQUE = "AARRGGBB"
private const val HEX = 16
