package com.pycompose.renderer

import androidx.compose.foundation.interaction.FocusInteraction
import androidx.compose.foundation.interaction.HoverInteraction
import androidx.compose.foundation.interaction.Interaction
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.PressInteraction
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import com.pycompose.ir.AppBinding
import com.pycompose.ir.generated.IrContract
import kotlinx.coroutines.flow.collect
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.longOrNull

/**
 * The host-created interaction source for one node, or null when it observes nothing.
 *
 * The source belongs to the host and lives exactly as long as the node: remembering
 * it by node id means pulling a new snapshot re-renders the tree without restarting
 * an interaction in flight. Session state leaves through [observation] and can never
 * drive a same-frame visual -- the reaction a user sees stays the component's own,
 * and the app learns about the interaction a frame later.
 *
 * @param id Stable node id the source's lifetime follows.
 * @param actionIds Action observing each interaction kind; null or absent means none.
 * @param observation Receives the kind, the action id and the new session state.
 */
@Composable
internal fun rememberInteractionSource(
    id: String,
    actionIds: Map<String, String?>,
    observation: (String, String, Boolean) -> Unit,
): MutableInteractionSource? {
    if (actionIds.values.none { it != null }) return null
    val source = remember(id) { MutableInteractionSource() }
    // The declaration is read fresh at dispatch rather than keyed into the
    // collection: an app that starts observing mid-session must not restart the
    // node's source and lose an interaction already in flight.
    val current = rememberUpdatedState(actionIds)
    LaunchedEffect(source) {
        source.interactions.collect { interaction ->
            val (kind, state) = kindAndState(interaction) ?: return@collect
            val actionId = current.value[kind] ?: return@collect
            observation(kind, actionId, state)
        }
    }
    return source
}

/**
 * The kind and session state one interaction reports, or null for one nobody observes.
 *
 * @param interaction The foundation interaction the source emitted.
 */
private fun kindAndState(interaction: Interaction): Pair<String, Boolean>? =
    when (interaction) {
        is PressInteraction.Press -> "press" to true
        is PressInteraction.Release,
        is PressInteraction.Cancel,
        -> "press" to false
        is FocusInteraction.Focus -> "focus" to true
        is FocusInteraction.Unfocus -> "focus" to false
        is HoverInteraction.Enter -> "hover" to true
        is HoverInteraction.Exit -> "hover" to false
        else -> null
    }

/**
 * Turns one observed interaction into an action, or reports why it cannot be one.
 *
 * The observation carries one primitive, and exactly one field of the declared
 * payload whose type fits that primitive receives it; two would mean the host
 * picked a field the app did not mean. A boolean fits boolean fields, an
 * integer satisfies both numeric declarations, and a float needs a number one.
 * The declaration is data, so nothing here needs the renderer or the
 * composition: the sink is testable on its own.
 *
 * @param bindings Session bindings by action id.
 * @param actions Dispatcher that receives the action.
 * @param report Sink for a message the host cannot turn into an action.
 */
internal class ObservationSink(
    private val bindings: Map<String, AppBinding>,
    private val actions: ActionDispatcher,
    private val report: (String) -> Unit,
) {
    /**
     * Report one observed boolean, as the rail's settled flags.
     *
     * @param kind Interaction kind the action observes, for the message.
     * @param actionId The action observing it.
     * @param value The new state of that kind.
     */
    fun observe(
        kind: String,
        actionId: String,
        value: Boolean,
    ) = observe(kind, actionId, JsonPrimitive(value))

    /**
     * Report one observed integer, as the lazy list's settled index.
     *
     * @param kind Interaction kind the action observes, for the message.
     * @param actionId The action observing it.
     * @param value The new state of that kind.
     */
    fun observe(
        kind: String,
        actionId: String,
        value: Int,
    ) = observe(kind, actionId, JsonPrimitive(value))

    /**
     * Report one observed float, as the slider's settled value.
     *
     * @param kind Interaction kind the action observes, for the message.
     * @param actionId The action observing it.
     * @param value The new state of that kind.
     */
    fun observe(
        kind: String,
        actionId: String,
        value: Float,
    ) = observe(kind, actionId, JsonPrimitive(value))

    /**
     * Report one observed primitive under the single field its type fits.
     *
     * @param kind Interaction kind the action observes, for the message.
     * @param actionId The action observing it.
     * @param value The new state of that kind, as wire data.
     */
    fun observe(
        kind: String,
        actionId: String,
        value: JsonPrimitive,
    ) {
        val fields =
            bindings[actionId]?.eventFields ?: IrContract.actionPayloads[actionId].orEmpty()
        val types =
            when {
                value.isString -> setOf("string")
                value.booleanOrNull != null -> setOf("boolean")
                value.longOrNull != null -> setOf("integer", "number")
                else -> setOf("number")
            }
        val candidates = fields.filterValues { it.type in types }
        val field = candidates.keys.singleOrNull()
        if (field == null) {
            report(
                "Cannot observe $kind for $actionId: " +
                    "${candidates.size} ${types.joinToString("/")} fields " +
                    "among ${fields.keys}",
            )
            return
        }
        actions.dispatch(actionId, JsonObject(mapOf(field to value)))
    }
}
