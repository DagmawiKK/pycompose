package com.pycompose.renderer

import androidx.compose.material3.SwipeToDismissBoxState
import androidx.compose.material3.SwipeToDismissBoxValue
import androidx.compose.material3.rememberSwipeToDismissBoxState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import com.pycompose.renderer.generated.driveTo

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
    val initial =
        remember { value?.anchor<SwipeToDismissBoxValue>() ?: SwipeToDismissBoxValue.Settled }
    val state = rememberSwipeToDismissBoxState(initialValue = initial)
    Reconcile(
        state,
        value,
        rememberSaveable { mutableStateOf(value) },
        settled = { state.settledValue.wire },
        report = report?.let { id -> { anchor -> observation("value", id, anchor) } },
    ) { it.anchor<SwipeToDismissBoxValue>()?.let { anchor -> state.driveTo(anchor) } }
    return state
}
