package com.pycompose.renderer

import androidx.compose.foundation.text.input.TextFieldState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.text.TextRange
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * An editing projection over a native [TextFieldState]. Selection offsets are UTF-16 code
 * units, as in Compose.
 *
 * The rule is [Edited]'s: every edit is reported numbered, and what the app states replaces
 * the field's only once the app has answered every edit. Equal editing values never interrupt
 * IME composition.
 *
 * @param text Desired text.
 * @param report Action receiving the complete editing value.
 * @param selectionStart Anchor of the desired selection, clamped to the text.
 * @param selectionEnd Active end of the desired selection, clamped to the text.
 */
@Composable
fun RenderContext.textInputState(
    text: String,
    report: String,
    selectionStart: Long,
    selectionEnd: Long,
): TextFieldState {
    val wanted =
        EditingValue(
            text,
            TextRange(
                selectionStart.toInt().coerceIn(0, text.length),
                selectionEnd.toInt().coerceIn(0, text.length),
            ),
        )
    val projection = remember { EditingProjection(wanted) }
    val answered = LocalAnswered.current
    val sink =
        rememberUpdatedState { value: EditingValue ->
            observations.observe(
                "textInput",
                report,
                buildJsonObject {
                    put("text", value.text)
                    put("selectionStart", value.selection.start)
                    put("selectionEnd", value.selection.end)
                },
            )
        }
    LaunchedEffect(projection, wanted, answered) {
        // A native edit can precede this statement while snapshotFlow is still waiting
        // to observe it; reported first, it is numbered, and the statement waits for it.
        projection.observe(projection.current(), sink.value)
        if (answered(report)) projection.drive(wanted)
    }
    LaunchedEffect(projection) {
        snapshotFlow { projection.current() }.collect { value ->
            projection.observe(value, sink.value)
        }
    }
    return projection.state
}

private data class EditingValue(
    val text: String,
    val selection: TextRange,
)

private class EditingProjection(
    initial: EditingValue,
) {
    val state = TextFieldState(initial.text, initial.selection)

    /** The value both sides know: the last one reported, or the last one applied. */
    private var baseline = initial

    fun current() = EditingValue(state.text.toString(), state.selection)

    fun drive(value: EditingValue) {
        baseline = value
        if (current() != value) {
            state.edit {
                if (toString() != value.text) replace(0, length, value.text)
                selection = value.selection
            }
        }
    }

    fun observe(
        value: EditingValue,
        report: (EditingValue) -> Unit,
    ) {
        if (value == baseline) return
        baseline = value
        report(value)
    }
}
