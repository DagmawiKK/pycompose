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
 * A revisioned editing projection. Selection offsets are UTF-16 code units, as in Compose.
 *
 * Python echoes each edit's revision with its text and range. Older echoes cannot undo
 * newer native edits; an equal revision can normalize an acknowledged edit. Deliberate
 * app commands use a greater revision. Equal editing values never interrupt IME composition.
 *
 * @param text Desired text.
 * @param report Action receiving the complete editing value.
 * @param selectionStart Anchor of the desired selection, clamped to the text.
 * @param selectionEnd Active end of the desired selection, clamped to the text.
 * @param revision Last acknowledged edit or a greater app-command revision.
 */
@Composable
fun RenderContext.textInputState(
    text: String,
    report: String,
    selectionStart: Long,
    selectionEnd: Long,
    revision: Long,
): TextFieldState {
    val wanted =
        EditingValue(
            text,
            TextRange(
                selectionStart.toInt().coerceIn(0, text.length),
                selectionEnd.toInt().coerceIn(0, text.length),
            ),
        )
    val projection =
        remember {
            EditingProjection(wanted, revision) {
                renderer.report("Text revision exhausted; use a new node id")
            }
        }
    val sink =
        rememberUpdatedState { value: EditingValue, serial: Long ->
            observations.observe(
                "textInput",
                report,
                buildJsonObject {
                    put("text", value.text)
                    put("selectionStart", value.selection.start)
                    put("selectionEnd", value.selection.end)
                    put("revision", serial)
                },
            )
        }
    LaunchedEffect(projection, wanted, revision) {
        // A native edit can precede this acknowledgement while snapshotFlow is
        // still waiting to observe it. Account for it before comparing revisions.
        projection.observeCurrent(sink.value)
        projection.drive(wanted, revision)
    }
    LaunchedEffect(projection) {
        snapshotFlow { EditingValue(projection.state.text.toString(), projection.state.selection) }
            .collect { value -> projection.observe(value, sink.value) }
    }
    return projection.state
}

private data class EditingValue(
    val text: String,
    val selection: TextRange,
)

private class EditingProjection(
    initial: EditingValue,
    initialRevision: Long,
    private val exhausted: () -> Unit,
) {
    val state = TextFieldState(initial.text, initial.selection)
    private var baseline = initial
    private var revision = initialRevision
    private var request = initial to initialRevision

    fun observeCurrent(report: (EditingValue, Long) -> Unit) {
        observe(EditingValue(state.text.toString(), state.selection), report)
    }

    fun drive(
        value: EditingValue,
        serial: Long,
    ) {
        if (request == value to serial) return
        request = value to serial
        if (serial < revision) return
        revision = serial
        baseline = value
        apply(value)
    }

    private fun apply(value: EditingValue) {
        if (state.text.toString() != value.text || state.selection != value.selection) {
            state.edit {
                if (toString() != value.text) replace(0, length, value.text)
                selection = value.selection
            }
        }
    }

    fun observe(
        value: EditingValue,
        report: (EditingValue, Long) -> Unit,
    ) {
        if (value == baseline) return
        if (revision == Long.MAX_VALUE) {
            apply(baseline)
            exhausted()
            return
        }
        baseline = value
        revision += 1
        report(value, revision)
    }
}
