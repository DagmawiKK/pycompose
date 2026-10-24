package com.pycompose.renderer

import androidx.compose.runtime.Composable
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
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
 * @param write Writes the property.
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
    wire: (V) -> JsonElement,
) {
    Reconcile(
        state,
        desired,
        remember(state, name) { mutableStateOf<Wanted<V>?>(null) },
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
