package com.pycompose.renderer

import androidx.compose.foundation.text.input.TextFieldState
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.SearchBarState
import androidx.compose.material3.SearchBarValue
import androidx.compose.material3.rememberSearchBarState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.snapshotFlow
import androidx.compose.runtime.staticCompositionLocalOf

/**
 * The native state one search owner shares with every surface below it.
 *
 * A search bar is one editing surface shown at two sizes: the collapsed bar and
 * the expanded results surface. Material 3 threads the same `TextFieldState`
 * and `SearchBarState` through both, so the text, selection, revision and
 * expansion survive the transition. The owner creates the pair once; each
 * nested declaration reads it from [LocalHostSearchState] instead of creating
 * a second one.
 *
 * @param text The revisioned editing state the owner drives.
 * @param bar The native expansion state the owner drives and reports.
 */
@OptIn(ExperimentalMaterial3Api::class)
class HostSearchState internal constructor(
    val text: TextFieldState,
    val bar: SearchBarState,
)

/**
 * The search state of the nearest enclosing owner, or null outside one.
 *
 * The owner provides this around the native surfaces it composes, so a
 * declaration in its input or expanded slot receives the owner's state without
 * a registry and without leaking between sibling search bars. A nested owner
 * overrides it for its own subtree.
 */
val LocalHostSearchState = staticCompositionLocalOf<HostSearchState?> { null }

/**
 * The host-owned expansion state for one search node, reconciled to the app's desired value.
 *
 * A search bar expands from a tap, a focus change or the keyboard, and collapses
 * from a dismissal gesture; the native state owns both animations. The holder
 * therefore drives only a *change* of the app's desired value and reports each
 * native transition, treating the report as the new baseline so the app's echo
 * of it cannot re-drive the animation.
 *
 * @param expanded Desired expansion; null leaves expansion to native gestures.
 * @param report Action id expansion changes report to; null reports none.
 * @param observation Receives the observed value, the action id and its state.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun rememberHostSearchBarState(
    expanded: Boolean?,
    report: String?,
    observation: (String, String, Boolean) -> Unit,
): SearchBarState {
    // Seeding from the first composition only, rather than from a changing
    // remember key, keeps the state alive when the app flips the value: the
    // flip is a drive the native animation carries, not a new holder.
    val initial =
        remember {
            if (expanded == true) SearchBarValue.Expanded else SearchBarValue.Collapsed
        }
    val state = rememberSearchBarState(initialValue = initial)
    val lastDesired = remember(state) { mutableStateOf(expanded) }
    val settled = remember(state) { Settled(state.currentValue) }
    val channel = rememberUpdatedState(report)
    LaunchedEffect(state, expanded) {
        if (expanded != lastDesired.value) {
            lastDesired.value = expanded
            when (expanded) {
                true -> state.animateToExpanded()
                false -> state.animateToCollapsed()
                null -> Unit
            }
        }
    }
    LaunchedEffect(state) {
        snapshotFlow { state.currentValue }.collect { value ->
            if (value != settled.value) {
                settled.value = value
                val now = value == SearchBarValue.Expanded
                lastDesired.value = now
                channel.value?.let { observation("expanded", it, now) }
            }
        }
    }
    return state
}
