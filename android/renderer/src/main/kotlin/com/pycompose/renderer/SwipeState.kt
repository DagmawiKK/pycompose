package com.pycompose.renderer

import androidx.compose.material3.SwipeToDismissBoxState
import androidx.compose.material3.SwipeToDismissBoxValue
import androidx.compose.material3.rememberSwipeToDismissBoxState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.snapshotFlow

/**
 * The host-owned swipe state for one node, reconciled to the app's desired anchor.
 *
 * A swipe box has three anchors -- settled, dismissed towards the end, or
 * dismissed towards the start. The holder is remembered under the node's key and
 * created at the anchor the first composition states, so a snapshot pull neither
 * recreates a gesture in flight nor animates the opening state. A *change* of
 * the desired anchor drives the native state; the anchor the holder actually
 * settles on is reported, including a gesture the app did not cause. The report
 * reads [SwipeToDismissBoxState.settledValue], never the closest anchor during
 * a drag.
 *
 * A native change also becomes the report baseline, as it does for a tooltip:
 * the app's echo of the settled anchor cannot re-drive a swipe the user just
 * completed. The same baseline survives restoration through [rememberSaveable].
 *
 * @param value Desired anchor; null leaves the state to gestures.
 * @param report Action id settled anchors report to; null reports none.
 * @param observation Receives the observed value, the action id and its state.
 */
@Composable
internal fun rememberHostSwipeState(
    value: String?,
    report: String?,
    observation: (String, String, String) -> Unit,
): SwipeToDismissBoxState {
    val initial = remember { value?.toSwipeValue() ?: SwipeToDismissBoxValue.Settled }
    val state = rememberSwipeToDismissBoxState(initialValue = initial)
    val lastDesired = rememberSaveable { mutableStateOf<String?>(value) }
    val settled = remember(state) { mutableStateOf(state.settledValue) }
    val channel = rememberUpdatedState(report)
    val currentObservation = rememberUpdatedState(observation)
    LaunchedEffect(state, value) {
        if (value != lastDesired.value) {
            lastDesired.value = value
            when (value?.toSwipeValue()) {
                SwipeToDismissBoxValue.Settled -> state.reset()
                SwipeToDismissBoxValue.StartToEnd ->
                    state.dismiss(SwipeToDismissBoxValue.StartToEnd)
                SwipeToDismissBoxValue.EndToStart ->
                    state.dismiss(SwipeToDismissBoxValue.EndToStart)
                null -> Unit
            }
        }
    }
    LaunchedEffect(state) {
        snapshotFlow { state.settledValue }.collect { native ->
            if (native != settled.value) {
                settled.value = native
                lastDesired.value = native.toWireValue()
                channel.value?.let { currentObservation.value("value", it, native.toWireValue()) }
            }
        }
    }
    return state
}

/** The native anchor a wire value names, or null when the host cannot know it. */
private fun String.toSwipeValue(): SwipeToDismissBoxValue? =
    when (this) {
        "settled" -> SwipeToDismissBoxValue.Settled
        "startToEnd" -> SwipeToDismissBoxValue.StartToEnd
        "endToStart" -> SwipeToDismissBoxValue.EndToStart
        else -> null
    }

/** The lowerCamel wire spelling of a native anchor. */
private fun SwipeToDismissBoxValue.toWireValue(): String =
    when (this) {
        SwipeToDismissBoxValue.Settled -> "settled"
        SwipeToDismissBoxValue.StartToEnd -> "startToEnd"
        SwipeToDismissBoxValue.EndToStart -> "endToStart"
    }
