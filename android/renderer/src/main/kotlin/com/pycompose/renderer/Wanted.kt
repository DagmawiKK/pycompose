package com.pycompose.renderer

import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
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
        answered = answered(report),
    ) { write(it.value) }
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
