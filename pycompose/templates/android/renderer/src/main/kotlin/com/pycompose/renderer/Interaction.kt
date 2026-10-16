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
import kotlinx.coroutines.flow.collect

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
