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
 * The holder's factory, its settled anchor and its drive are the pin's ([Anchors]); what a
 * family decides is only how its anchor is spelled on the wire and whether the holder starts at
 * the first desired value.
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

/**
 * How the pin makes, reads and drives one anchored holder, generated per holder class.
 *
 * @property values Each anchor, by its wire spelling.
 * @property create The holder's pinned factory, at an anchor or at its own start.
 * @property settled Reads the anchor the holder has settled on.
 * @property drive Moves the holder to an anchor through its pinned member.
 */
data class Anchors<V : Any, H : Any>(
    val values: Map<String, V>,
    val create: @Composable (V?) -> H,
    val settled: (H) -> V,
    val drive: suspend (H, V) -> Unit,
)

/**
 * The node's anchored holder -- a drawer open or closed, a swipe settled or dismissed, any
 * holder of one enum the pin derives -- reporting the anchor it settles on.
 *
 * The holder is created at the first anchor stated, so a pull neither recreates a gesture in
 * flight nor animates the opening state, and that anchor is no report.
 *
 * @param desired Desired anchor, as the wire spells it; null leaves the holder to gestures.
 * @param report Action id settled anchors report to; null reports none.
 * @param anchors How the pin makes, reads and drives this holder.
 * @return The holder.
 */
@Composable
fun <V : Any, H : Any> RenderContext.anchoredState(
    desired: String?,
    report: String?,
    anchors: Anchors<V, H>,
): H {
    val initial = remember { desired?.let(anchors.values::get) }
    val state = anchors.create(initial)
    val spelled =
        remember(anchors.values) {
            anchors.values.entries.associate { (key, value) ->
                value to
                    key
            }
        }
    anchored(
        state,
        desired,
        seeded = true,
        settled = { spelled.getValue(anchors.settled(state)) },
        report = report,
        field = "value",
        wire = ::JsonPrimitive,
    ) { anchor -> anchors.values[anchor]?.let { anchors.drive(state, it) } }
    return state
}
