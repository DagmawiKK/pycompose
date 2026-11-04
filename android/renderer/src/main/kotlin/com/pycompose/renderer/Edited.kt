package com.pycompose.renderer

import androidx.compose.runtime.Composable
import androidx.compose.runtime.Stable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import kotlinx.serialization.json.JsonPrimitive

/**
 * A value the user edits and the app owns: what a text field shows.
 *
 * Every edit is reported with the next number for its action, and each snapshot echoes the
 * latest number the app answered ([Reports]). A snapshot published before the app answered
 * every edit states a value older than the field's, so the field keeps what the user typed: one
 * that showed it would apply the next keystroke to text keys old. Once the app has answered,
 * what the snapshot states is the app's own -- its echo, or text it cleared or rewrote -- and
 * replaces the field's. The numbers decide, never a comparison of values, so an app that answers
 * "ab" with "a" is shown "a".
 */
@Stable
class Edited<V> internal constructor(
    initial: V,
) {
    /** What the field shows. */
    var value by mutableStateOf(initial)
        private set

    internal fun show(value: V) {
        this.value = value
    }
}

/**
 * The node's edited value, told what its current snapshot states.
 *
 * @param id The node's id, which the value's lifetime follows.
 * @param stated What the snapshot states.
 * @param reports The actions the field reports its edits to; a null one reports nothing.
 * @return The value the field shows.
 */
@Composable
fun <V> RenderContext.edited(
    id: String,
    stated: V,
    vararg reports: String?,
): Edited<V> {
    val edited = remember(id) { Edited(stated) }
    if (reports.all { answered(it) } && edited.value != stated) edited.show(stated)
    return edited
}

/**
 * The user edited the field: show [value] at once, and report it to [actionId] numbered, so
 * the app's answer can be told from a snapshot that predates it.
 *
 * @param edited The field's edited value.
 * @param value What the field now holds.
 * @param actionId The action receiving the edit.
 * @param wire The edit as the action's payload carries it.
 */
fun <V> RenderContext.edit(
    edited: Edited<V>,
    value: V,
    actionId: String,
    wire: JsonPrimitive,
) = edit(edited, value, mapOf(actionId to wire))

/**
 * As the single-action overload, for a field that reports one edit to several actions (its
 * text to one, its caret to another); an edit that changed neither reports nothing.
 *
 * @param edited The field's edited value.
 * @param value What the field now holds.
 * @param reports Each action the edit reaches, with its payload.
 */
fun <V> RenderContext.edit(
    edited: Edited<V>,
    value: V,
    reports: Map<String, JsonPrimitive>,
) {
    edited.show(value)
    reports.forEach { (actionId, wire) -> observations.observe("edit", actionId, wire) }
}
