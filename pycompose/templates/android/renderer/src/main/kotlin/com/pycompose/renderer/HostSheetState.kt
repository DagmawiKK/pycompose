package com.pycompose.renderer

import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.SheetState
import androidx.compose.material3.SheetValue
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.MutableState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.saveable.listSaver
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import com.pycompose.renderer.generated.driveTo
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.isActive
import kotlinx.serialization.json.JsonPrimitive

/**
 * A sheet's data-only projections, with the explicit anchor taking precedence over [open].
 *
 * Native measurement defines the available anchors. Opening first lets the component's
 * own show effect finish; a requested detent is then reconciled without reporting that
 * intermediate opening. Hidden is absence of composition, never an invisible dialog.
 *
 * @param contract The declared desired presence and anchors, with their reports.
 * @param skipPartiallyExpanded Native holder policy; null keeps the native false default.
 * @param observations Sink the two declared reports dispatch through.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun rememberHostSheetState(
    contract: SheetContract,
    skipPartiallyExpanded: Boolean?,
    observations: ObservationSink,
): HostSheetState {
    val skipPartial = skipPartiallyExpanded ?: false
    val state = rememberModalBottomSheetState(skipPartiallyExpanded = skipPartial)
    val desired = contract.value ?: contract.open?.let { if (it) VISIBLE_REQUEST else "hidden" }
    val memory =
        rememberSaveable(stateSaver = SheetMemory.saver) {
            mutableStateOf(SheetMemory(dismissed = false, request = null))
        }
    // Native-holder bookkeeping resets with the holder's skip policy, but the
    // app's dismissal and request survive that recreation.
    val driveMemory =
        rememberSaveable(skipPartial, stateSaver = SheetDriveMemory.saver) {
            mutableStateOf(SheetDriveMemory(settled = state.currentValue, pending = null))
        }
    // The live presence keeps the sheet composed through a hide animation. On
    // restoration it is rebuilt from the snapshot: a hide in flight, an old
    // dismissed sheet, or a hidden request must not reopen the saved anchor.
    val open =
        remember(state, skipPartial) {
            mutableStateOf(desired != null && desired != "hidden" && !memory.value.dismissed)
        }
    val projection =
        remember(state, memory, driveMemory, open) {
            SheetProjection(state, memory, driveMemory, open)
        }
    DriveSheet(projection, desired, answered(contract.report) && answered(contract.valueReport))
    ObserveSheet(projection, contract.report, contract.valueReport, observations)
    ObserveDismissal(projection)
    return HostSheetState(state, open.value)
}

/** The declared sheet contract, grouped so the holder's signature stays narrow. */
internal data class SheetContract(
    val open: Boolean?,
    val report: String?,
    val value: String?,
    val valueReport: String?,
)

/** What survives process death and a holder recreation: the app's intent. */
private data class SheetMemory(
    val dismissed: Boolean,
    val request: String?,
) {
    companion object {
        val saver =
            listSaver<SheetMemory, Any?>(
                save = { listOf(it.dismissed, it.request) },
                restore = { saved -> SheetMemory(saved[0] as Boolean, saved[1] as String?) },
            )
    }
}

/** What survives process death for one native holder: its baseline and drive. */
@OptIn(ExperimentalMaterial3Api::class)
private data class SheetDriveMemory(
    val settled: SheetValue,
    val pending: String?,
) {
    companion object {
        val saver =
            listSaver<SheetDriveMemory, Any?>(
                save = { listOf(it.settled.name, it.pending) },
                restore = { saved ->
                    SheetDriveMemory(
                        SheetValue.valueOf(saved[0] as String),
                        saved[1] as String?,
                    )
                },
            )
    }
}

/** One native emission the observer may commit, including a failed opening. */
@OptIn(ExperimentalMaterial3Api::class)
private data class SheetSnapshot(
    val anchor: SheetValue,
    val settled: SheetValue,
    val animating: Boolean,
    val driving: Boolean,
    val failed: Boolean,
)

/** The legacy boolean request's internal spelling; never a native anchor. */
private const val VISIBLE_REQUEST = "visible"

/** Reconciliation bookkeeping, scoped to the node's remembered native holder. */
@OptIn(ExperimentalMaterial3Api::class)
private class SheetProjection(
    val state: SheetState,
    private val memory: MutableState<SheetMemory>,
    private val driveMemory: MutableState<SheetDriveMemory>,
    private val open: MutableState<Boolean>,
) {
    var driving by mutableStateOf(false)
    var failedToOpen by mutableStateOf(false)
    var settled: SheetValue
        get() = driveMemory.value.settled
        set(value) {
            if (driveMemory.value.settled != value) {
                driveMemory.value = driveMemory.value.copy(settled = value)
            }
        }
    var pending: String?
        get() = driveMemory.value.pending
        set(value) {
            if (driveMemory.value.pending != value) {
                driveMemory.value = driveMemory.value.copy(pending = value)
            }
        }
    var dismissed: Boolean
        get() = memory.value.dismissed
        set(value) {
            if (memory.value.dismissed != value) {
                memory.value = memory.value.copy(dismissed = value)
            }
        }
    var reattach =
        when {
            !visible -> null
            // A save mid-drive re-drives the stated request, not the anchor the
            // native holder happened to reach before the save.
            pending != null -> pending
            state.currentValue != SheetValue.Hidden -> state.currentValue.wire
            // Saved during the opening animation: the request must still reconcile.
            else -> lastDesired?.takeIf { it != "hidden" }
        }

    val visible: Boolean get() = open.value
    val lastDesired: String? get() = memory.value.request

    fun present(visible: Boolean) {
        open.value = visible
        dismissed = !visible
    }

    fun request(request: String?) {
        memory.value = memory.value.copy(request = request)
    }
}

/** Drive once per changed request; native show owns measurement and opening. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun DriveSheet(
    projection: SheetProjection,
    stated: String?,
    answered: Boolean,
) {
    OnDesired(projection, stated, answered) { desired ->
        val changed = desired != projection.lastDesired
        val restored = projection.reattach
        if (changed || restored != null) {
            val request = if (changed) desired else restored
            projection.reattach = null
            projection.request(desired)
            if (request != null) {
                projection.driving = true
                projection.pending = request
                try {
                    projection.drive(request, restored != null)
                } catch (cancelled: CancellationException) {
                    if (!currentCoroutineContext().isActive) throw cancelled
                    // A competing native gesture can cancel an anchor animation.
                    // Let the gesture settle; a hide is a failed visible request.
                    snapshotFlow { projection.state.isAnimationRunning }.first { !it }
                    if (projection.state.currentValue == SheetValue.Hidden) {
                        projection.present(false)
                        if (request != "hidden") projection.failedToOpen = true
                    }
                } finally {
                    projection.driving = false
                    projection.pending = null
                }
            }
        }
    }
}

/** Never invent a missing partial anchor or retain a hidden dialog window. */
@OptIn(ExperimentalMaterial3Api::class)
private suspend fun SheetProjection.drive(
    desired: String,
    reattaching: Boolean,
) {
    failedToOpen = false
    if (desired == "hidden") {
        // Run the native hide, and only then let the composed sheet leave the tree.
        if (visible && (state.currentValue != SheetValue.Hidden || state.isAnimationRunning)) {
            state.driveTo(SheetValue.Hidden)
        }
        present(false)
        return
    }
    // A visible request supersedes any dismissal that kept the last one absent.
    val opening = !visible || state.currentValue == SheetValue.Hidden || reattaching
    present(true)
    if (opening) awaitOpening()
    snapshotFlow { state.isAnimationRunning }.first { !it }
    if (state.currentValue == SheetValue.Hidden) {
        // A native dismissal may cancel the automatic opening; do not fight it,
        // but the app must learn that the visible request did not commit.
        present(false)
        failedToOpen = true
    } else {
        reconcile(desired)
    }
}

/** Wait for measurement and for the component's own show effect to start. */
@OptIn(ExperimentalMaterial3Api::class)
private suspend fun SheetProjection.awaitOpening() {
    snapshotFlow { state.hasExpandedState }.first { it }
    // A restored holder can already name the saved anchor before the component
    // starts its own show(). Await an animation or the actual opening anchor.
    snapshotFlow {
        val anchor =
            if (state.hasPartiallyExpandedState) {
                SheetValue.PartiallyExpanded
            } else {
                SheetValue.Expanded
            }
        state.isAnimationRunning || state.currentValue == anchor
    }.first { it }
}

/** Move to the requested visible anchor, or expanded where measurement has no partial one. */
@OptIn(ExperimentalMaterial3Api::class)
private suspend fun SheetProjection.reconcile(desired: String) {
    val target = desired.anchor<SheetValue>() ?: return
    val reachable =
        if (target == SheetValue.PartiallyExpanded && !state.hasPartiallyExpandedState) {
            SheetValue.Expanded
        } else {
            target
        }
    if (state.currentValue != reachable) {
        state.driveTo(reachable)
    } else if (reachable != target && settled == SheetValue.Expanded) {
        // Re-arm the baseline so the observer reports the actual anchor even
        // though it did not move.
        settled = SheetValue.PartiallyExpanded
    }
}

/** Both reports observe the same native commit; a detent change is not another open edge. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ObserveSheet(
    projection: SheetProjection,
    report: String?,
    valueReport: String?,
    observations: ObservationSink,
) {
    val openChannel = rememberUpdatedState(report)
    val valueChannel = rememberUpdatedState(valueReport)
    val sink = rememberUpdatedState(observations)
    LaunchedEffect(projection) {
        val state = projection.state
        snapshotFlow {
            SheetSnapshot(
                state.currentValue,
                projection.settled,
                state.isAnimationRunning,
                projection.driving,
                projection.failedToOpen,
            )
        }.collect { snapshot ->
            if (snapshot.animating || snapshot.driving) return@collect
            if (snapshot.failed) {
                projection.failedToOpen = false
                if (snapshot.anchor == SheetValue.Hidden) {
                    projection.settled = SheetValue.Hidden
                    projection.present(false)
                    valueChannel.value?.let {
                        sink.value.observe("value", it, JsonPrimitive(SheetValue.Hidden.wire))
                    }
                    openChannel.value?.let { sink.value.observe("open", it, JsonPrimitive(false)) }
                    return@collect
                }
            }
            if (snapshot.anchor != snapshot.settled) {
                val wasOpen = snapshot.settled != SheetValue.Hidden
                val isOpen = snapshot.anchor != SheetValue.Hidden
                projection.settled = snapshot.anchor
                projection.present(isOpen)
                valueChannel.value?.let {
                    sink.value.observe("value", it, JsonPrimitive(snapshot.anchor.wire))
                }
                if (wasOpen != isOpen) {
                    openChannel.value?.let { sink.value.observe("open", it, JsonPrimitive(isOpen)) }
                }
            }
        }
    }
}

/**
 * Persist a native hide as soon as it starts, not after it settles: a save in
 * the middle of the gesture must not restore the sheet the user dismissed.
 * A gesture cancelled back to a visible target clears the mark.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ObserveDismissal(projection: SheetProjection) {
    LaunchedEffect(projection) {
        snapshotFlow { projection.state.targetValue to projection.driving }
            .collect { (target, driving) ->
                if (!driving && projection.state.currentValue != SheetValue.Hidden) {
                    projection.dismissed = target == SheetValue.Hidden
                }
            }
    }
}

/**
 * One node's native holder and presence gate, consumed by generated adapters.
 *
 * @param state The native state the component reads and drives.
 * @param visible Whether the adapter should compose the sheet at all.
 */
@OptIn(ExperimentalMaterial3Api::class)
class HostSheetState internal constructor(
    val state: SheetState,
    val visible: Boolean,
)
