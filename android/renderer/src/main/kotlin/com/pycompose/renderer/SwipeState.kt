package com.pycompose.renderer

import androidx.compose.material3.SwipeToDismissBoxState
import androidx.compose.material3.SwipeToDismissBoxValue
import androidx.compose.material3.rememberSwipeToDismissBoxState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable

/**
 * The host-owned swipe state for one node, reconciled to the app's desired anchor.
 *
 * A swipe box has three anchors -- settled, dismissed towards the end, or
 * dismissed towards the start. The holder is created at the anchor the first
 * composition states, so a snapshot pull neither recreates a gesture in flight
 * nor animates the opening state, and its last desired anchor survives
 * restoration. The report reads [SwipeToDismissBoxState.settledValue], never the
 * closest anchor during a drag.
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
    Reconcile(
        state,
        value,
        rememberSaveable { mutableStateOf(value) },
        settled = { state.settledValue.toWireValue() },
        report = report?.let { id -> { anchor -> observation("value", id, anchor) } },
    ) {
        when (val anchor = it.toSwipeValue()) {
            SwipeToDismissBoxValue.Settled -> state.reset()
            null -> Unit
            else -> state.dismiss(anchor)
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
