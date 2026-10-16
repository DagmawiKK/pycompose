package com.pycompose.renderer

import androidx.compose.material3.DrawerState
import androidx.compose.material3.DrawerValue
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.SheetState
import androidx.compose.material3.SheetValue
import androidx.compose.material3.rememberDrawerState
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.mutableStateOf
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
private class Settled<T>(
    var value: T,
)

/**
 * The host-owned sheet state for one node, and whether the host composes it.
 *
 * A sheet is a drawer in every way but one, and that one is not a detail: the
 * native component shows itself as soon as it is composed and measured, and
 * while composed it keeps a window in front of the app even at rest. Presence
 * is therefore the host's too: a sheet the app wants shown is composed, one
 * that has settled hidden is not, and [HostSheetState.visible] is that
 * decision.
 *
 * Driving only on a *change* of the desired value is the whole protocol, as it
 * is for a drawer: the app's own close runs the hide, a gesture runs the hide,
 * and either settled change is reported with `open` as its field.
 *
 * @param open Desired state; null leaves the state to the app's gestures.
 * @param report Action id settled changes report to; null reports none.
 * @param observation Receives the observed value, the action id and its state.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun rememberHostSheetState(
    open: Boolean?,
    report: String?,
    observation: (String, String, Boolean) -> Unit,
): HostSheetState {
    val state = rememberModalBottomSheetState(skipPartiallyExpanded = false)
    val visible = remember(state) { mutableStateOf(open == true) }
    val settled = remember(state) { Settled(state.currentValue) }
    LaunchedEffect(state, open) {
        when (open) {
            // Composing the sheet is the drive: the component shows itself.
            true -> visible.value = true
            // Hiding is the host's to run, and it suspends until the sheet has
            // settled, so the component is never dropped out from under its own
            // animation. An already-hidden state runs no animation at all.
            false -> {
                if (state.currentValue != SheetValue.Hidden) {
                    state.hide()
                }
                visible.value = false
            }
            null -> Unit
        }
    }
    val channel = rememberUpdatedState(report)
    LaunchedEffect(state) {
        // A report is a change from the value composition found, as for a
        // drawer; and a hidden sheet leaves the composition, which is why the
        // settled value decides presence too.
        snapshotFlow { state.currentValue }.collect { value ->
            if (value != settled.value) {
                settled.value = value
                visible.value = value != SheetValue.Hidden
                channel.value?.let {
                    observation("open", it, value != SheetValue.Hidden)
                }
            }
        }
    }
    return HostSheetState(state, visible.value)
}

/**
 * One sheet node's held state, and whether the host should compose the sheet.
 *
 * Public because the generated adapter asks the question of it; the
 * constructor stays the renderer's.
 *
 * @param state The native state the component reads and drives.
 * @param visible Whether the adapter should compose the component at all.
 */
@OptIn(ExperimentalMaterial3Api::class)
class HostSheetState internal constructor(
    val state: SheetState,
    val visible: Boolean,
)
