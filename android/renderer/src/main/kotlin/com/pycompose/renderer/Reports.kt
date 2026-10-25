package com.pycompose.renderer

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.compositionLocalOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.saveable.rememberSaveable

/**
 * The host's half of report sequencing.
 *
 * Each settled value a holder reports takes the next number for its action, and each
 * snapshot echoes the latest number the app answered ([com.pycompose.ir.Echoes]). A
 * report the app has not answered yet means the snapshot's desired value answers an
 * older one, so a holder must not drive towards it: a late echo of "open" would
 * reopen a drawer the user has since closed. The numbers live as long as the renderer,
 * across snapshots, and are snapshot state so a holder notices when its echo arrives.
 */
internal class Reports {
    private val sent = mutableStateMapOf<String, Long>()

    /** The next number for a report to [actionId]. */
    fun next(actionId: String): Long = ((sent[actionId] ?: 0L) + 1).also { sent[actionId] = it }

    /** Whether [echoes] answer every report sent to [actionId]. */
    fun answered(
        actionId: String,
        echoes: Map<String, Long>,
    ): Boolean = (echoes[actionId] ?: 0L) >= (sent[actionId] ?: 0L)
}

/** Whether the app has answered every report to an action; true outside a renderer. */
internal val LocalAnswered = compositionLocalOf<(String) -> Boolean> { { true } }

/** Whether a holder reporting to [report] may drive towards the app's desired value now. */
@Composable
internal fun answered(report: String?): Boolean = report == null || LocalAnswered.current(report)

/**
 * Run [apply] when the app states a new desired value, once the app has answered every
 * report the holder sent.
 *
 * A value stated while a report is unanswered answers an older report, so it waits; when
 * the answer arrives, the value current then is applied. The answer arriving is never a
 * reason on its own to move the holder, and a drive in flight is never cancelled by a
 * report it causes: only a newly stated value restarts [apply].
 *
 * The last stated value survives saved-state restoration with the holder itself, so after
 * a rotation or process death the restored native state stands unless the app now states
 * something different: one owner, the app's statements, across every lifetime.
 *
 * @param state The node's native holder; both effects are keyed to it.
 * @param desired The app's desired value; saveable, as every holder's value is.
 * @param answered Whether the app has answered every report the holder sent.
 * @param keepsStatements False for a holder that saves its own last request and must see
 *   every restoration, as the sheet does to show its window again.
 * @param apply Moves the holder towards a desired value it does not already rest at.
 */
@Composable
internal fun <V> OnDesired(
    state: Any,
    desired: V,
    answered: Boolean,
    keepsStatements: Boolean = true,
    apply: suspend (V) -> Unit,
) {
    val current = rememberUpdatedState(desired)
    val waiting = remember(state) { Settled(false) }
    val stated = rememberSaveable { mutableStateOf<V?>(null) }
    val seen = rememberSaveable { mutableStateOf(false) }

    suspend fun state(value: V) {
        waiting.value = false
        seen.value = true
        stated.value = value
        apply(value)
    }
    LaunchedEffect(state, desired) {
        when {
            keepsStatements && seen.value && desired == stated.value -> waiting.value = false
            answered -> state(desired)
            else -> waiting.value = true
        }
    }
    LaunchedEffect(state, answered) {
        if (answered && waiting.value) state(current.value)
    }
}
