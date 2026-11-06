package com.pycompose.renderer

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import com.pycompose.ir.OptionalValue
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * A desired property value, which may itself be null: `selectedDateMillis`
 * clears to null. A null [Wanted] means the app states nothing.
 *
 * Serializable because the last statement is saved with the holder (see
 * [OnDesired]); properties are scalars, which a saved-state bundle carries.
 */
data class Wanted<V>(
    val value: V,
) : java.io.Serializable

/** An optional nullable prop as a desired value: absent states nothing, null clears. */
fun <V> OptionalValue.wanted(decode: (JsonPrimitive) -> V): Wanted<V?>? =
    when (this) {
        OptionalValue.Absent -> null
        OptionalValue.Null -> Wanted(null)
        is OptionalValue.Present -> Wanted(decode(value as JsonPrimitive))
    }

/**
 * One property of a holder the pin derives a family for (`TimePickerState.hour`),
 * reconciled as every family is: a *change* of the desired value writes it, and
 * each settled value is reported once (see [Reconcile]).
 *
 * @param state The node's remembered holder.
 * @param name The property, which is also the report's payload field.
 * @param desired The app's desired value; null states nothing.
 * @param report Action id settled values report to; null reports none.
 * @param read Reads the property.
 * @param write Writes the property, or re-creates a seeded holder at it.
 * @param seeded Whether the holder was created at the desired value (see
 *   [Reseed]), which then counts as driven: a re-created holder must not
 *   re-create itself again.
 * @param answering The report whose answers the desired value waits for: its own, or the
 *   holder's settle report where the holder reports there (see [reportSettled]).
 * @param wire Spells a value on the wire.
 */
@Suppress("LongParameterList")
@Composable
fun <V> RenderContext.reconcileProperty(
    state: Any,
    name: String,
    desired: Wanted<V>?,
    report: String?,
    read: () -> V,
    write: (V) -> Unit,
    seeded: Boolean = false,
    answering: String? = report,
    wire: (V) -> JsonElement,
) {
    Reconcile(
        state,
        desired,
        remember(state, name) { mutableStateOf(if (seeded) desired else null) },
        settled = { Wanted(read()) },
        report =
            report?.let { id ->
                { settled ->
                    observations.observe(
                        name,
                        id,
                        JsonObject(
                            mapOf(
                                name to wire(settled.value),
                            ),
                        ),
                    )
                }
            },
        answered = answered(answering),
    ) { write(it.value) }
}

/**
 * A holder's values reported where the holder says they settle -- a slider's
 * `onValueChangeFinished` -- rather than on every change: the app hears where a drag ended,
 * never each frame of it, and hears it once. A drive reports through the check this returns,
 * called after it writes: the holder may have made something else of the value (a tick).
 *
 * @param state The node's remembered holder; a re-created one is given the callback again.
 * @param report Action id the settled values report to; null reports none.
 * @param install Sets the holder's settle callback.
 * @param values The holder's values now, as the report's payload.
 * @return Reports the values if they changed since the last report.
 */
@Composable
fun RenderContext.reportSettled(
    state: Any,
    report: String?,
    install: (() -> Unit) -> Unit,
    values: () -> JsonObject,
): () -> Unit {
    val channel = rememberUpdatedState(report)
    val reported = remember(state) { Settled(values()) }
    val check =
        remember(state) {
            {
                val now = values()
                if (now != reported.value) {
                    reported.value = now
                    channel.value?.let { observations.observeAsked("settled", it, now) }
                }
            }
        }
    LaunchedEffect(state) { install(check) }
    return check
}

/**
 * A holder re-created through its factory whenever a seeded property is driven.
 *
 * The factory sets what a property's setter does not: `TimePickerState.hour`
 * moves the number, but only `rememberTimePickerState(initialHour)` places the
 * dial's hand. The adapter composes the factory under [generation], seeding
 * each property the app leaves unstated from [previous].
 */
class Reseed<H : Any> {
    /** Bumped on every drive; the adapter keys the factory call to it. */
    var generation by mutableIntStateOf(0)
        private set

    /** The holder the current one replaced, or null for the first. */
    var previous: H? = null
        private set

    /** Replace [holder] with a new one created at the app's desired values. */
    fun from(holder: H) {
        previous = holder
        generation++
    }
}
