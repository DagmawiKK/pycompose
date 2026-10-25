package com.pycompose.host.ui

import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.text.TextRange
import androidx.compose.ui.text.input.TextFieldValue

/**
 * Text the app owns while the user types it.
 *
 * Every keystroke is reported to Python, and its snapshot echoes the text back
 * a little later. A field that showed the snapshot's text would apply the next
 * keystroke to text one or more keys old, dropping what was typed in between:
 * "Groceries" typed quickly arrived as "Grocies". So the field shows the latest
 * keystroke, and a snapshot replaces it only when it is not the echo of a value
 * already reported -- an app that clears or rewrites the text still does.
 *
 * The caret follows the text: the field keeps its own while the user types, and
 * takes the app's only with the app's own text. A snapshot's caret is as stale
 * as its text, so a field that took it would insert each key at an old place.
 */
internal class EchoedText(
    initial: String,
    caret: Int? = null,
) {
    /** The field's value: its text and its own selection. */
    var value by mutableStateOf(at(initial, caret))
        private set

    val text: String get() = value.text

    private val pending = ArrayDeque<String>()
    private var seen = initial

    /** The user typed [value]; it is reported, and its echo is now expected. */
    fun typed(value: String) = typed(TextFieldValue(value, TextRange(value.length)))

    /** The user edited the field, text and caret both; the text's echo is expected. */
    fun typed(value: TextFieldValue) {
        if (value.text != this.value.text) pending.addLast(value.text)
        this.value = value
    }

    /**
     * A snapshot stated [value], and where the app puts the caret in it.
     *
     * @return True when it is the app's own text, which now replaces the field's.
     */
    fun stated(
        value: String,
        caret: Int? = null,
    ): Boolean {
        val fresh = value != seen
        seen = value
        // An echo answers its keystroke and every older one: Python may have
        // coalesced several into one snapshot.
        val echo = pending.indexOf(value)
        val own = fresh && echo < 0
        if (fresh && echo >= 0) repeat(echo + 1) { pending.removeFirst() }
        if (own) {
            pending.clear()
            this.value = at(value, caret)
        }
        return own
    }
}

/** [text] with the caret where the app puts it, or at its end. */
private fun at(
    text: String,
    caret: Int?,
): TextFieldValue = TextFieldValue(text, TextRange((caret ?: text.length).coerceIn(0, text.length)))

/** The node's [EchoedText], told the text its current snapshot states. */
@Composable
internal fun rememberEchoedText(
    id: String,
    value: String,
    caret: Int? = null,
): EchoedText {
    val echoed = remember(id) { EchoedText(value, caret) }
    echoed.stated(value, caret)
    return echoed
}
