package com.pycompose.renderer

import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.PressInteraction
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import kotlinx.coroutines.flow.collect

/**
 * The host-created interaction source for one node, or null when it observes nothing.
 *
 * The source belongs to the host and lives exactly as long as the node: remembering
 * it by node id means pulling a new snapshot re-renders the tree without restarting
 * a ripple in flight. Press state leaves through [observation] and can never drive a
 * same-frame visual -- the reaction a user sees stays the component's own, and the
 * app learns about the press a frame later.
 *
 * @param id Stable node id the source's lifetime follows.
 * @param actionId Action observing press state, or null when the node observes none.
 * @param observation Receives the action id and the new press state.
 */
@Composable
internal fun rememberInteractionSource(
    id: String,
    actionId: String?,
    observation: (String, Boolean) -> Unit,
): MutableInteractionSource? {
    if (actionId == null) return null
    val source = remember(id) { MutableInteractionSource() }
    LaunchedEffect(source, actionId) {
        source.interactions.collect { interaction ->
            when (interaction) {
                is PressInteraction.Press -> observation(actionId, true)
                is PressInteraction.Release,
                is PressInteraction.Cancel,
                -> observation(actionId, false)
                else -> Unit
            }
        }
    }
    return source
}
