package com.pycompose.host

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.semantics.getOrNull
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.performTextInput
import com.pycompose.host.ui.BuiltinComponents
import com.pycompose.host.ui.PyComposeTheme
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
 * Typing faster than Python echoes loses no keystroke.
 *
 * Found on an emulator: "Groceries" typed quickly arrived as "Grocies",
 * because each key edited the last snapshot's text rather than the field's.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34], application = android.app.Application::class)
class TextFieldEchoTest {
    @get:Rule val compose = createComposeRule()

    private fun snapshot(
        value: String,
        caret: Int? = null,
    ): ValidatedIr =
        IrParser()
            .parse(
                """
                {"version":"0.1.0","schemaVersion":"1.23.0",
                 "metadata":{"intents":{"note.title":{"payload":{
                     "value":{"required":true,"type":"string"}}},"note.caret":{"payload":{
                     "value":{"required":true,"type":"integer"}}}}},
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

        // The echo of the first key arrives late: the field keeps "ab".
        stated = snapshot("a")
        compose.waitForIdle()
        assertEquals("ab", shown())

        // The app clears the note: that is its own text, not an echo.
        stated = snapshot("ab")
        compose.waitForIdle()
        stated = snapshot("")
        compose.waitForIdle()
        assertEquals("", shown())
    }

    @Test
    fun aGeneratedTextFieldKeepsKeysTypedBeforeTheEchoToo() {
        val actions = mutableListOf<Action>()
        val renderer = Renderer(BuiltinComponents.registry(), ActionDispatcher { actions.add(it) })

        fun outlined(value: String) =
            IrParser()
                .parse(
                    """
                    {"version":"0.1.0","schemaVersion":"1.23.0",
                     "metadata":{"intents":{"note.title":{"payload":{
                         "value":{"required":true,"type":"string"}}}}},
                     "root":{"id":"title","type":"OutlinedTextField","props":{
                       "value":"$value","onValueChange":{"fields":{},"intent":"note.title"}}}}
                    """.trimIndent(),
                ).getOrThrow()
        var stated by mutableStateOf(outlined(""))
        compose.setContent { PyComposeTheme { renderer.Render(stated) } }

        compose.onNode(hasSetTextAction()).performTextInput("a")
        compose.onNode(hasSetTextAction()).performTextInput("b")
        stated = outlined("a")
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

        stated = snapshot("a", caret = 1)
        compose.waitForIdle()
        compose.onNode(hasSetTextAction()).performTextInput("d")
        compose.waitForIdle()
        assertEquals("abcd", shown())
    }
}
