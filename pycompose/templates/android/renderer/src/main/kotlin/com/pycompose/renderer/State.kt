package com.pycompose.renderer

import androidx.compose.material3.DrawerState
import androidx.compose.material3.DrawerValue
import androidx.compose.material3.rememberDrawerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.snapshotFlow

/**
 * The host-owned drawer state for one node, reconciled to the app's desired value.
 *
 * The state belongs to the host and lives exactly as long as the node: it is
 * remembered under the node's key, so pulling a snapshot re-renders the tree
 * without recreating state a gesture is already moving. Python states the
 * desired value in the snapshot; the host drives the state towards it, gestures
 * and animation included, and reports each settled change as an action.
 *
 * Driving only on a *change* of the desired value is the whole protocol:
 * re-asserting the value on every snapshot would fight a user who just swiped
 * the drawer shut, and that change is exactly what the report tells the app.
 *
 * @param open Desired state; null leaves the state to the app's gestures.
 * @param report Action id settled changes report to; null reports none.
 * @param observation Receives the observed value, the action id and its state.
 */
@Composable
internal fun rememberHostDrawerState(
    open: Boolean?,
    report: String?,
    observation: (String, String, Boolean) -> Unit,
): DrawerState {
    val state = rememberDrawerState(DrawerValue.Closed)
    val settled = remember(state) { Settled(state.currentValue) }
    LaunchedEffect(state, open) {
        when (open) {
            true -> state.open()
            false -> state.close()
            null -> Unit
        }
    }
    val channel = rememberUpdatedState(report)
    LaunchedEffect(state) {
        // A report is a change from the value composition found. Seeding the
        // baseline here would lose the first one: a drawer without anchors yet
        // settles in the same dispatch as the drive, before this flow's first
        // read.
        snapshotFlow { state.currentValue }.collect { value ->
            if (value != settled.value) {
                settled.value = value
                channel.value?.let { observation("open", it, value == DrawerValue.Open) }
            }
        }
    }
    return state
}

/** The settled value one node last reported, seeded where its composition started. */
private class Settled(
    var value: DrawerValue,
)
