package com.pycompose.host.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.semantics.getOrNull
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.performTextInput
import com.pycompose.host.intent
import com.pycompose.ir.IrParser
import com.pycompose.ir.ValidatedIr
import com.pycompose.renderer.Action
import com.pycompose.renderer.ActionDispatcher
import com.pycompose.renderer.Renderer
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/**
 * Typing faster than Python answers loses no keystroke, and the app's answer still stands.
 *
 * Found on an emulator: "Groceries" typed quickly arrived as "Grocies", because each key
 * edited the last snapshot's text rather than the field's. Each key is reported numbered,
 * and a snapshot echoes the latest number the app answered: until it answers them all, the
 * field keeps what was typed; once it has, what it states is its own.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34], application = android.app.Application::class)
class TextFieldEchoTest {
    @get:Rule val compose = createComposeRule()

    /** The answers a snapshot echoes: the latest number per intent; 0 echoes none. */
    private fun echoes(vararg answered: Pair<String, Int>): String {
        val echoed = answered.filter { (_, seq) -> seq > 0 }
        if (echoed.isEmpty()) return ""
        return echoed.joinToString(",", ""","echoes":[""", "]") { (intent, seq) ->
            """{"seq":$seq,"target":{"fields":{},"intent":"$intent"}}"""
        }
    }

    private fun snapshot(
        value: String,
        caret: Int? = null,
        vararg answered: Pair<String, Int>,
    ): ValidatedIr =
        IrParser()
            .parse(
                """
                {"version":"0.1.0","schemaVersion":"1.23.0",
                 "metadata":{"intents":{"note.title":{"payload":{
                     "value":{"required":true,"type":"string"}}},"note.caret":{"payload":{
                     "value":{"required":true,"type":"integer"}}}}${echoes(*answered)}},
                 "root":{"id":"title","type":"TextField","props":{
                   "value":"$value","label":"Title","onValueChange":{"fields":{},
                     "intent":"note.title"}
                   ${caret?.let {
                    ""","selection":$it,"onSelectionChange":{"fields":{},"intent":"note.caret"}"""
                } ?: ""}}}}
                """.trimIndent(),
            ).getOrThrow()

    private fun shown(): String? =
        compose
            .onNode(hasSetTextAction())
            .fetchSemanticsNode()
            .config
            .getOrNull(SemanticsProperties.EditableText)
            ?.text

    @Test
    fun keysTypedBeforeTheEchoAreKeptAndTheAppCanStillClearTheField() {
        val actions = mutableListOf<Action>()
        val renderer = Renderer(BuiltinComponents.registry(), ActionDispatcher { actions.add(it) })
        var stated by mutableStateOf(snapshot(""))
        compose.setContent { PyComposeTheme { renderer.Render(stated) } }

        // Two keys before any snapshot answers the first.
        compose.onNode(hasSetTextAction()).performTextInput("a")
        compose.onNode(hasSetTextAction()).performTextInput("b")
        compose.waitForIdle()
        assertEquals("ab", shown())
        assertEquals(
            listOf("a", "ab"),
            actions.filter { it.actionId == intent("note.title") }.map {
                it.payload["value"].toString().trim('"')
            },
        )

        // The answer to the first key arrives while the second is unanswered: "ab" stays.
        stated = snapshot("a", null, "note.title" to 1)
        compose.waitForIdle()
        assertEquals("ab", shown())

        // The app answered both and refused the second key: its word stands, though
        // "a" is a value the user once typed.
        stated = snapshot("a", null, "note.title" to 2)
        compose.waitForIdle()
        assertEquals("a", shown())

        // The app clears the note.
        stated = snapshot("", null, "note.title" to 2)
        compose.waitForIdle()
        assertEquals("", shown())
    }

    @Test
    fun aGeneratedTextFieldKeepsKeysTypedBeforeTheEchoToo() {
        val actions = mutableListOf<Action>()
        val renderer = Renderer(BuiltinComponents.registry(), ActionDispatcher { actions.add(it) })

        fun outlined(
            value: String,
            seq: Int,
        ) = IrParser()
            .parse(
                """
                    {"version":"0.1.0","schemaVersion":"1.23.0",
                     "metadata":{"intents":{"note.title":{"payload":{
                         "value":{"required":true,"type":"string"}}}}${echoes(
                    "note.title" to seq,
                )}},
                     "root":{"id":"title","type":"OutlinedTextField","props":{
                       "value":"$value","onValueChange":{"fields":{},"intent":"note.title"}}}}
                """.trimIndent(),
            ).getOrThrow()
        var stated by mutableStateOf(outlined("", 0))
        compose.setContent { PyComposeTheme { renderer.Render(stated) } }

        compose.onNode(hasSetTextAction()).performTextInput("a")
        compose.onNode(hasSetTextAction()).performTextInput("b")
        stated = outlined("a", 1)
        compose.waitForIdle()
        assertEquals("ab", shown())
    }

    @Test
    fun aControlledCaretStaysWhereTheUserTypesUntilTheAppMovesIt() {
        val actions = mutableListOf<Action>()
        val renderer = Renderer(BuiltinComponents.registry(), ActionDispatcher { actions.add(it) })
        var stated by mutableStateOf(snapshot("", caret = 0))
        compose.setContent { PyComposeTheme { renderer.Render(stated) } }

        // The snapshot's caret (0) is stale while keys are in flight: each key
        // must still land after the last, not at the snapshot's old position.
        compose.onNode(hasSetTextAction()).performTextInput("a")
        compose.onNode(hasSetTextAction()).performTextInput("b")
        compose.onNode(hasSetTextAction()).performTextInput("c")
        compose.waitForIdle()
        assertEquals("abc", shown())

        // An answer to the first key only: text and caret both stay the field's.
        stated = snapshot("a", 1, "note.title" to 1, "note.caret" to 1)
        compose.waitForIdle()
        compose.onNode(hasSetTextAction()).performTextInput("d")
        compose.waitForIdle()
        assertEquals("abcd", shown())
    }
}
