package com.pycompose.renderer

import androidx.compose.runtime.Composable
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import kotlinx.serialization.json.JsonPrimitive

/**
 * A holder whose value is one of its anchors -- a drawer open or closed, a swipe settled or
 * dismissed -- reconciled as every family is (see [Reconcile]).
 *
 * The holder's factory, its settled anchor and its drive are the pin's (`rememberAnchored`,
 * `settledAnchor`, `driveTo`); what a family decides is only how its anchor is spelled on the
 * wire and whether the holder starts at the first desired value.
 *
 * @param state The node's holder, created by its pinned factory.
 * @param desired The app's desired value in wire terms; null drives nothing.
 * @param seeded Whether [state] was created at [desired]: the first statement is then no
 *   change, and the last desired value survives restoration with the holder.
 * @param settled Reads the settled anchor in wire terms.
 * @param report Action id settled values report to; null reports none.
 * @param field The report's payload field.
 * @param wire Spells a value on the wire.
 * @param drive Moves the holder towards a desired value.
 */
@Suppress("LongParameterList")
@Composable
internal fun <V : Any> RenderContext.anchored(
    state: Any,
    desired: V?,
    seeded: Boolean,
    settled: () -> V,
    report: String?,
    field: String,
    wire: (V) -> JsonPrimitive,
    drive: suspend (V) -> Unit,
) {
    val lastDesired =
        if (seeded) {
            rememberSaveable { mutableStateOf(desired) }
        } else {
            remember(state) { mutableStateOf<V?>(null) }
        }
    Reconcile(
        state,
        desired,
        lastDesired,
        settled,
        report = report?.let { id -> { value -> observations.observe(field, id, wire(value)) } },
        answered = answered(report),
        drive = drive,
    )
}
