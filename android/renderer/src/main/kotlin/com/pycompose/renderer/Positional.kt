package com.pycompose.renderer

import androidx.compose.foundation.gestures.ScrollableState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.saveable.rememberSaveable

/**
 * How the pin makes, reads and drives one positional holder, generated per holder class.
 *
 * @property create The holder's pinned factory, at a start and with the count.
 * @property position Reads the holder's position.
 * @property drive Moves the holder to a position through its pinned member.
 */
data class Positional<H : ScrollableState>(
    val create: @Composable (Int, () -> Int) -> H,
    val position: (H) -> Int,
    val drive: suspend (H, Int) -> Unit,
)

/**
 * The node's positional holder -- a pager's page, a carousel's item, any holder with one
 * scrollable position the pin derives. The app states the position it wants and the host
 * drives there; the position it settles on, by gesture or by drive, is reported once scrolling
 * comes to rest. Its positions are the children Python sent.
 *
 * @param desired Desired position; null leaves scrolling to gestures.
 * @param report Action id settled positions report to; null reports none.
 * @param count How many positions there are, read whenever the holder asks.
 * @param holder How the pin makes, reads and drives this holder.
 * @return The holder.
 */
@Composable
fun <H : ScrollableState> RenderContext.positional(
    desired: Long?,
    report: String?,
    count: Int,
    holder: Positional<H>,
): H {
    val (create, position, drive) = holder
    val positions = rememberUpdatedState(count)
    val state = create(desired?.toInt() ?: 0) { positions.value }
    val lastDesired = rememberSaveable { mutableStateOf<Long?>(null) }
    OnDesired(state, desired, answered(report)) { wanted ->
        if (wanted != lastDesired.value) {
            val target = wanted?.toInt()?.coerceIn(0, (positions.value - 1).coerceAtLeast(0))
            if (target != null && target != position(state)) drive(state, target)
            lastDesired.value = wanted
        }
    }
    ObserveIdlePosition(state, { position(state) }, "position", report, observations::observe)
    return state
}
