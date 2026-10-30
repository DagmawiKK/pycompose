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

/*
 * A holder publishes the numbers it exposes -- a drawer's open fraction, a
 * scroll's offset and fraction -- under its node's id, read from its public
 * properties only. Expressions read them during composition, so the reading
 * adapter recomposes as they move and Python never runs per frame.
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
