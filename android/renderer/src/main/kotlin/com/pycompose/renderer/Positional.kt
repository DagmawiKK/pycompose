package com.pycompose.renderer

import androidx.compose.animation.core.AnimationSpec
import androidx.compose.foundation.gestures.ScrollableState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.saveable.rememberSaveable
import com.pycompose.program.Phase
import com.pycompose.program.Travel
import kotlinx.serialization.json.JsonElement

/**
 * How the pin makes, reads and drives one positional holder, generated per holder class.
 *
 * @property create The holder's pinned factory, at a start and with the count.
 * @property position Reads the holder's position.
 * @property snap Moves the holder without animating, for a followed position; null where the
 *   pin offers no binding.
 * @property drive Moves the holder to a position through its pinned member, with a spec where
 *   the app's binding travels.
 */
data class Positional<H : ScrollableState>(
    val create: @Composable (Int, () -> Int) -> H,
    val position: (H) -> Int,
    val snap: (suspend (H, Int) -> Unit)?,
    val drive: suspend (H, Int, AnimationSpec<Float>?) -> Unit,
)

/**
 * The node's positional holder -- a pager's page, a list's first visible item, a scroll's
 * offset, any holder with one scrollable position the pin derives. The app states the position
 * it wants and the host drives there; the holder bounds it, and the position it settles on, by
 * gesture or by drive, is reported once scrolling comes to rest.
 *
 * A bound position travels: `animate` moves through the drive with its spec, `follow` tracks
 * through the snap. A gesture interrupts either as it interrupts any drive, and the position it
 * leaves is reported; an answer to an older report waits, so it never pulls the holder back.
 *
 * @param desired Desired position, plain or bound; null leaves scrolling to gestures.
 * @param report Action id settled positions report to; null reports none.
 * @param count How many children Python sent, read whenever a counting holder asks.
 * @param holder How the pin makes, reads and drives this holder.
 * @return The holder.
 */
@Composable
fun <H : ScrollableState> RenderContext.positional(
    desired: JsonElement?,
    report: String?,
    count: Int,
    holder: Positional<H>,
): H {
    val (create, position) = holder
    val binding = desired?.let(::bound)?.at(Phase.Composition)
    val wanted = (binding?.target ?: desired)?.let { number(it).toLong() }
    val travel = rememberUpdatedState(binding?.travel)
    val children = rememberUpdatedState(count)
    val state = create(wanted?.toInt() ?: 0) { children.value }
    val lastDesired = rememberSaveable { mutableStateOf<Long?>(null) }
    OnDesired(state, wanted, answered(report)) { next ->
        if (next != lastDesired.value) {
            // Recorded before driving: a gesture cancels the drive, and the rest it leaves is
            // judged against what the app asked.
            lastDesired.value = next
            val target = next?.toInt()
            if (target != null && target != position(state)) {
                val snap = holder.snap
                when (val by = travel.value) {
                    null -> holder.drive(state, target, null)
                    Travel.None ->
                        checkNotNull(
                            snap,
                        ) { "This position cannot follow" }(state, target)
                    else -> holder.drive(state, target, spec(by))
                }
            }
        }
    }
    ObserveIdlePosition(state, {
        position(state)
    }, "position", report, observations::observe, lastDesired)
    return state
}
