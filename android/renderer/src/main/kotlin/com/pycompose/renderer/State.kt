package com.pycompose.renderer

import androidx.compose.foundation.ScrollState
import androidx.compose.foundation.gestures.ScrollableState
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.DrawerState
import androidx.compose.material3.DrawerValue
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.SheetState
import androidx.compose.material3.SheetValue
import androidx.compose.material3.SliderState
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.TooltipState
import androidx.compose.material3.rememberDrawerState
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.material3.rememberTooltipState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.saveable.Saver
import androidx.compose.runtime.saveable.listSaver
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.snapshotFlow
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Modifier
import kotlinx.coroutines.flow.collectLatest
import kotlinx.serialization.json.JsonPrimitive

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
internal class Settled<T>(
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

/**
 * The host-owned slider state for one node, reconciled to the app's desired value.
 *
 * The holder is remembered under the node's key and constructed from the range
 * and the step count the app states, so a new snapshot re-renders the tree
 * without recreating a drag in flight. A *change* of the desired value moves
 * the value through the public value setter, and the
 * holder coerces the result into its own range. A gesture settles through
 * [SliderState.onValueChangeFinished], which is where the report rides: the app
 * hears settled values, never each frame of a drag the host did not cause.
 *
 * @param value Desired value; null starts the holder at the range's floor.
 * @param report Action id settled values report to; null reports none.
 * @param valueRange The holder's range; null uses the native floor-to-one.
 * @param steps Step count between range bounds; null uses none.
 * @param observation Receives the observed value, the action id and its state.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun rememberHostSliderState(
    value: Double?,
    report: String?,
    valueRange: ClosedFloatingPointRange<Float>?,
    steps: Long?,
    observation: (String, String, Float) -> Unit,
): SliderState {
    val range = valueRange ?: (0f..1f)
    val count = (steps ?: 0L).toInt()
    val saver =
        remember(range, count) {
            Saver<SliderState, Float>(
                save = { it.value },
                restore = { SliderState(value = it, steps = count, valueRange = range) },
            )
        }
    val state =
        rememberSaveable(range.start, range.endInclusive, count, saver = saver) {
            SliderState(
                value = range.start,
                steps = count,
                valueRange = range,
            )
        }
    val channel = rememberUpdatedState(report)
    val currentObservation = rememberUpdatedState(observation)
    val lastDesired =
        rememberSaveable(range.start, range.endInclusive, count) {
            mutableStateOf<Double?>(null)
        }
    val settled = remember(state) { Settled(state.value) }
    val reportSettled = {
        val current = state.value
        if (current != settled.value) {
            settled.value = current
            channel.value?.let { action -> currentObservation.value("value", action, current) }
        }
    }
    LaunchedEffect(state) { state.onValueChangeFinished = reportSettled }
    LaunchedEffect(state, value) {
        if (value != lastDesired.value) {
            val desired = value?.toFloat()
            if (desired != null && desired != state.value) {
                state.value = desired
                reportSettled()
            }
            lastDesired.value = value
        }
    }
    return state
}

/**
 * The host-owned tooltip state for one node, reconciled to the app's desired value.
 *
 * A tooltip has no settled callback of its own: hover, focus and long press show
 * it through the native state, an outside click dismisses it, and a
 * non-persistent tooltip closes on its own timer. The holder therefore reports
 * the *visible* transition rather than a gesture callback, and treats a native
 * change as the new baseline so the app's echo of that change cannot re-show a
 * tooltip the user just dismissed.
 *
 * @param visible Desired visibility; null leaves the tooltip to its gestures.
 * @param isPersistent Whether the native tooltip waits for an explicit dismissal.
 * @param report Action id visibility changes report to; null reports none.
 * @param observation Receives the observed value, the action id and its state.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun rememberHostTooltipState(
    visible: Boolean?,
    isPersistent: Boolean,
    report: String?,
    observation: (String, String, Boolean) -> Unit,
): TooltipState {
    val state = rememberTooltipState(isPersistent = isPersistent)
    val lastDesired = remember(state) { mutableStateOf<Boolean?>(null) }
    val settled = remember(state) { Settled(state.isVisible) }
    val channel = rememberUpdatedState(report)
    val currentObservation = rememberUpdatedState(observation)
    LaunchedEffect(state, visible) {
        if (visible != lastDesired.value) {
            lastDesired.value = visible
            when (visible) {
                true -> {
                    // Let the anchor's initial unfocused notification run first:
                    // native keyboard handling dismisses a visible tooltip there.
                    withFrameNanos { }
                    state.show()
                }
                false -> state.dismiss()
                null -> Unit
            }
        }
    }
    LaunchedEffect(state) {
        snapshotFlow { state.isVisible }.collect { value ->
            if (value != settled.value) {
                settled.value = value
                lastDesired.value = value
                channel.value?.let { currentObservation.value("visible", it, value) }
            }
        }
    }
    return state
}

/**
 * The host-owned scroll state for one node, reconciled to the app's desired offset.
 *
 * A scroll has no settled callback of its own: it settles when the fling
 * ends, so the report rides the idle transition and only when the offset
 * differs from the one composition found. A change of the desired offset
 * scrolls the holder there; the scroll's own progress makes that a settled
 * change like any other, and the app hears it back.
 *
 * @param offset Desired offset in pixels; null leaves the scroll to gestures.
 * @param report Action id settled offsets report to; null reports none.
 * @param observation Receives the observed value, the action id and its state.
 */
@Composable
internal fun rememberHostScrollState(
    offset: Double?,
    report: String?,
    observation: (String, String, Int) -> Unit,
): ScrollState {
    // Top, like the drawer starts closed: a stated offset is a drive from
    // there, and the drive's own settle is what reports the arrival.
    val state = rememberScrollState(initial = 0)
    val lastDesired = rememberSaveable { mutableStateOf<Double?>(null) }
    LaunchedEffect(state, offset) {
        if (offset != lastDesired.value) {
            val desired = offset?.toInt()
            if (desired != null && desired != state.value) {
                state.scrollTo(desired)
            }
            lastDesired.value = offset
        }
    }
    ObserveIdlePosition(state, { state.value }, "offset", report, observation)
    return state
}

/**
 * The modifier carrying this scroll, or the plain one when the app asked for none.
 *
 * A scroll holder fills no native parameter: it rides the component's own
 * modifier behind the boolean prop the app states, so a column that never
 * asked to scroll is exactly the column it was before.
 *
 * @param modifier The component's other modifier contributions.
 * @param scrollable Whether the app asked for this column to scroll.
 */
fun ScrollState.attachTo(
    modifier: Modifier,
    scrollable: Boolean?,
): Modifier = if (scrollable == true) modifier.verticalScroll(this) else modifier

/**
 * The host-owned lazy list state for one node, reconciled to the desired index.
 *
 * The holder is remembered under the node's key; a change of the desired index
 * scrolls the list there through the suspending call, and the settled index
 * reports when the scroll ends -- an item the app asked for lands at the top
 * exactly once, and a user's own fling reports where it came to rest.
 *
 * @param index Desired first visible item; null leaves the list to gestures.
 * @param report Action id settled indexes report to; null reports none.
 * @param observation Receives the observed value, the action id and its state.
 */
@Composable
internal fun rememberHostLazyListState(
    index: Long?,
    report: String?,
    observation: (String, String, Int) -> Unit,
): LazyListState {
    val state = rememberLazyListState()
    val lastDesired = rememberSaveable { mutableStateOf<Long?>(null) }
    LaunchedEffect(state, index) {
        if (index != lastDesired.value) {
            val desired = index?.toInt()
            if (
                desired != null &&
                (desired != state.firstVisibleItemIndex || state.firstVisibleItemScrollOffset != 0)
            ) {
                state.scrollToItem(desired)
            }
            lastDesired.value = index
        }
    }
    ObserveIdlePosition(state, {
        state.firstVisibleItemIndex
    }, "firstVisibleIndex", report, observation)
    return state
}

/** One idle policy for both native scroll holders, including drag-to-fling hand-off. */
@Composable
private fun ObserveIdlePosition(
    state: ScrollableState,
    position: () -> Int,
    kind: String,
    report: String?,
    observation: (String, String, Int) -> Unit,
) {
    val currentPosition = rememberUpdatedState(position)
    val currentObservation = rememberUpdatedState(observation)
    val channel = rememberUpdatedState(report)
    val settled = remember(state) { Settled(position()) }
    LaunchedEffect(state, kind) {
        // Including position catches synchronous drives which enter and leave
        // scrolling before a flow read. Only a settled position leaves the host.
        snapshotFlow { state.isScrollInProgress to currentPosition.value() }
            .collectLatest { (inProgress, value) ->
                if (inProgress) return@collectLatest
                // Native drag release may precede the fling in the same frame.
                withFrameNanos { }
                if (
                    !state.isScrollInProgress &&
                    value == currentPosition.value() &&
                    value != settled.value
                ) {
                    settled.value = value
                    channel.value?.let {
                        currentObservation.value(kind, it, value)
                    }
                }
            }
    }
}

/**
 * The request one transient node's host is answering, fixed when its serial appears.
 *
 * @param message The content to show.
 * @param actionLabel Optional action to offer beside it.
 * @param onDismiss Action id the fulfilled serial reports to; null reports none.
 * @param serial The request's serial, compared against the last one handled.
 */
internal data class SnackbarRequest(
    val message: String,
    val actionLabel: String?,
    val onDismiss: String?,
    val serial: Long,
)

private val snackbarRequestSaver =
    listSaver<SnackbarRequest, Any?>(
        save = { listOf(it.message, it.actionLabel, it.onDismiss, it.serial) },
        restore = {
            SnackbarRequest(it[0] as String, it[1] as String?, it[2] as String?, it[3] as Long)
        },
    )

/**
 * The host-owned snackbar holder for one node, showing each serial exactly once.
 *
 * A transient has no settled state to compare against, so the serial is the
 * whole protocol: an identical re-rendered snapshot names the same serial and
 * the remembered request never changes, so nothing re-shows; a bumped serial
 * replaces the request and the effect runs again; and when the snackbar has
 * been dismissed or its action answered, the occurrence reports the fulfilled
 * serial back under the node's identity so Python can correlate the answer
 * with the request it made. A serial never handled below the last one shown is
 * an old request arriving late, and it is dropped rather than replayed.
 *
 * @param id Stable node id the holder's lifetime follows.
 * @param request Content, serial and occurrence channel of the app's request.
 * @param observation Receives the kind, the action id and the fulfilled serial.
 */
@Composable
internal fun rememberHostSnackbar(
    id: String,
    request: SnackbarRequest,
    observation: (String, String, JsonPrimitive) -> Unit,
): SnackbarHostState {
    val state = remember(id) { SnackbarHostState() }
    // Keep the highest accepted request before keying the effect. Rejecting an
    // old serial inside the effect is too late: changing its key has already
    // cancelled the snackbar that was showing.
    val latest =
        rememberSaveable(id, stateSaver = snackbarRequestSaver) {
            mutableStateOf(request)
        }
    val fulfilled = rememberSaveable(id) { mutableStateOf<Long?>(null) }
    if (request.serial > latest.value.serial) {
        latest.value = request
    }
    val accepted = latest.value
    LaunchedEffect(state, accepted) {
        if (fulfilled.value == accepted.serial) return@LaunchedEffect
        state.showSnackbar(
            message = accepted.message,
            actionLabel = accepted.actionLabel,
            withDismissAction = true,
        )
        fulfilled.value = accepted.serial
        accepted.onDismiss?.let {
            observation("dismiss", it, JsonPrimitive(accepted.serial))
        }
    }
    return state
}
