package com.pycompose.host

import androidx.activity.ComponentActivity
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertTextEquals
import androidx.compose.ui.test.hasAnyDescendant
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performImeAction
import androidx.compose.ui.test.performTextInput
import com.pycompose.host.ui.BuiltinComponents
import com.pycompose.host.ui.PyComposeTheme
import com.pycompose.ir.IrParser
import com.pycompose.ir.ValidatedIr
import com.pycompose.renderer.Action
import com.pycompose.renderer.ActionDispatcher
import com.pycompose.renderer.Renderer
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** One owner shares editing, selection and expansion with every nested surface. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34], application = android.app.Application::class)
class SharedSearchTest {
    @get:Rule val compose = createAndroidComposeRule<ComponentActivity>()
    private val actions = mutableListOf<Action>()
    private val diagnostics = mutableListOf<String>()
    private val renderer =
        Renderer(
            BuiltinComponents.registry(),
            ActionDispatcher { actions.add(it) },
            report = diagnostics::add,
        )

    @Test
    fun expandedSurfaceKeepsTheCollapsedFieldsTextAndSelection() {
        val current = mutableStateOf(snapshot())
        compose.setContent { PyComposeTheme { renderer.Render(current.value) } }
        val collapsed = compose.field("C")
        collapsed.assertTextEquals("compose")
        collapsed.performTextInput("x")
        compose.waitUntil(5000) { edits().size == 1 }
        assertEquals(JsonPrimitive("composex"), edits().last().payload["text"])
        assertEquals(JsonPrimitive(8), edits().last().payload["selectionStart"])

        compose.runOnIdle {
            current.value = snapshot(Edit("composex", 8, 8, 1), expanded = true)
        }
        val expanded = compose.field("E")
        expanded.assertTextEquals("composex")
        collapsed.assertTextEquals("composex")
        expanded.performClick()
        expanded.performTextInput("y")
        compose.waitUntil(5000) { edits().size == 2 }
        assertEquals(JsonPrimitive("composexy"), edits().last().payload["text"])
        assertEquals(JsonPrimitive(2), edits().last().payload["revision"])
        collapsed.assertTextEquals("composexy")

        expanded.performImeAction()
        compose.waitUntil(5000) { searches().isNotEmpty() }
        assertEquals(JsonPrimitive("composexy"), searches().last().payload["query"])
    }

    @Test
    fun nativeExpansionReportsOnceAndTheAppsEchoDoesNotRedriveIt() {
        val current = mutableStateOf(snapshot())
        compose.setContent { PyComposeTheme { renderer.Render(current.value) } }
        compose.field("C").performClick()
        compose.waitUntil(5000) { expansions().isNotEmpty() }
        assertEquals(listOf(JsonPrimitive(true)), expansions().map { it.payload["expanded"] })

        compose.runOnIdle { current.value = snapshot(expanded = true) }
        compose.waitForIdle()
        assertEquals(1, expansions().size)
        compose.field("E").assertExists()

        compose.runOnIdle { current.value = snapshot(expanded = false) }
        compose.waitUntil(5000) { expansions().size == 2 }
        assertEquals(JsonPrimitive(false), expansions().last().payload["expanded"])
        compose.runOnIdle { current.value = snapshot(expanded = false) }
        compose.waitForIdle()
        assertEquals(2, expansions().size)
        compose.field("E").assertDoesNotExist()
    }

    @Test
    fun nativeDismissalCollapsesAndReportsTheSettledValue() {
        val current = mutableStateOf(snapshot(expanded = true))
        compose.setContent { PyComposeTheme { renderer.Render(current.value) } }
        compose.field("E").assertExists()
        compose.runOnIdle { compose.activity.onBackPressedDispatcher.onBackPressed() }
        compose.waitUntil(5000) { expansions().isNotEmpty() }
        assertEquals(JsonPrimitive(false), expansions().last().payload["expanded"])
        compose.waitForIdle()
        compose.field("E").assertDoesNotExist()
        compose.field("C").assertExists()
    }

    @Test
    fun fullScreenSurfaceSharesTheSameEditingState() {
        val current = mutableStateOf(snapshot(kind = "ExpandedFullScreenSearchBar"))
        compose.setContent { PyComposeTheme { renderer.Render(current.value) } }
        compose.field("C").performTextInput("x")
        compose.waitUntil(5000) { edits().size == 1 }
        compose.runOnIdle {
            current.value =
                snapshot(
                    Edit("composex", 8, 8, 1),
                    expanded = true,
                    kind = "ExpandedFullScreenSearchBar",
                )
        }
        val expanded = compose.field("E")
        expanded.assertTextEquals("composex")
        expanded.performClick()
        expanded.performTextInput("y")
        compose.waitUntil(5000) { edits().size == 2 }
        assertEquals(JsonPrimitive("composexy"), edits().last().payload["text"])
        compose.field("C").assertTextEquals("composexy")
    }

    @Test
    fun siblingOwnersKeepTheirEditingStateApart() {
        compose.setContent { PyComposeTheme { renderer.Render(siblings()) } }
        val alpha = compose.onNode(hasSetTextAction() and hasText("alpha"))
        val beta = compose.onNode(hasSetTextAction() and hasText("beta"))
        alpha.assertExists()
        beta.assertExists()
        alpha.performTextInput("x")
        compose.waitUntil(5000) { edits().size == 1 }
        assertEquals(JsonPrimitive("alphax"), edits().last().payload["text"])

        beta.performTextInput("y")
        compose.waitUntil(5000) { edits().size == 2 }
        assertEquals(JsonPrimitive("betay"), edits().last().payload["text"])
    }

    @Test
    fun nativeFocusExpandsAnOwnerThatDoesNotStateExpansion() {
        val current = mutableStateOf(snapshot(controlled = false))
        compose.setContent { PyComposeTheme { renderer.Render(current.value) } }
        compose.field("C").performClick()
        compose.waitUntil(5000) { expansions().isNotEmpty() }
        assertEquals(JsonPrimitive(true), expansions().last().payload["expanded"])
        compose.field("E").assertExists()
    }

    @Test
    fun aStateFieldOutsideItsOwnerIsDiagnosedInsteadOfCrashing() {
        compose.setContent { PyComposeTheme { renderer.Render(orphan()) } }
        compose.waitForIdle()
        assertEquals(1, diagnostics.size)
        compose.onAllNodes(hasSetTextAction()).assertCountEquals(0)
    }

    private fun edits(): List<Action> = actions.filter { it.actionId == intent("demo.edit") }

    private fun searches(): List<Action> = actions.filter { it.actionId == intent("demo.search") }

    private fun expansions(): List<Action> = actions.filter { it.actionId == intent("demo.expand") }

    private fun androidx.compose.ui.test.junit4.ComposeContentTestRule.field(marker: String) =
        onNode(
            hasSetTextAction() and hasAnyDescendant(hasText(marker)),
            useUnmergedTree = true,
        )

    private data class Edit(
        val text: String = "compose",
        val start: Int = 7,
        val end: Int = 7,
        val revision: Long = 0,
    )

    private fun snapshot(
        edit: Edit = Edit(),
        expanded: Boolean = false,
        kind: String = "ExpandedDockedSearchBar",
        controlled: Boolean = true,
    ): ValidatedIr {
        val expansion = if (controlled) "\"expanded\":$expanded," else ""
        return IrParser()
            .parse(
                echoing(
                    """
                    {"version":"0.1.0","schemaVersion":"1.23.0",
                      "metadata":{"intents":{"demo.edit":{"payload":{
                        "text":{"type":"string","required":true},
                        "selectionStart":{"type":"integer","required":true},
                        "selectionEnd":{"type":"integer","required":true},
                        "revision":{"type":"integer","required":true}}},"demo.search":{"payload":{
                        "query":{"type":"string","required":true}}},"demo.expand":{"payload":{
                        "expanded":{"type":"boolean","required":true}}}}},
                     "root":{"id":"search","type":"StatefulSearchBar","props":{
                       "text":"${edit.text}","selectionStart":${edit.start},
                       "selectionEnd":${edit.end},"revision":${edit.revision},
                       "onEdit":{"fields":{},"intent":"demo.edit"},$expansion
                       "onExpandedChange":{"fields":{},"intent":"demo.expand"}},"children":[
                       {"id":"collapsed","type":"SearchBarStateInputField","slot":"inputField",
                         "props":{
                         "onSearch":{"fields":{},"intent":"demo.search"}},"children":[
                         {"id":"collapsed.icon","type":"Text","slot":"leadingIcon",
                           "props":{"text":"C"}}]},
                       {"id":"expanded","type":"$kind","slot":"expandedBar","props":{},"children":[
                         {"id":"expanded.input","type":"SearchBarStateInputField",
                           "slot":"inputField","props":{
                           "onSearch":{"fields":{},"intent":"demo.search"}},"children":[
                           {"id":"expanded.icon","type":"Text","slot":"leadingIcon",
                             "props":{"text":"E"}}]},
                         {"id":"result","type":"Text","props":{"text":"A result"}}]}]}}
                    """.trimIndent(),
                    actions,
                ),
            ).getOrThrow()
    }

    private fun siblings(): ValidatedIr =
        IrParser()
            .parse(
                echoing(
                    """
                    {"version":"0.1.0","schemaVersion":"1.23.0",
                      "metadata":{"intents":{"demo.edit":{"payload":{
                        "text":{"type":"string","required":true},
                        "selectionStart":{"type":"integer","required":true},
                        "selectionEnd":{"type":"integer","required":true},
                        "revision":{"type":"integer","required":true}}},"demo.expand":{"payload":{
                        "expanded":{"type":"boolean","required":true}}}}},
                     "root":{"id":"column","type":"Column","props":{},"children":[
                       {"id":"alpha","type":"StatefulSearchBar","props":{
                         "text":"alpha","selectionStart":5,"selectionEnd":5,"revision":0,
                         "onEdit":{"fields":{},"intent":"demo.edit"},"expanded":false,
                         "onExpandedChange":{"fields":{},"intent":"demo.expand"}},"children":[
                         {"id":"alpha.input","type":"SearchBarStateInputField","slot":"inputField",
                           "props":{
                           "onSearch":{"fields":{},"intent":"demo.expand"}}}]},
                       {"id":"beta","type":"StatefulSearchBar","props":{
                         "text":"beta","selectionStart":4,"selectionEnd":4,"revision":0,
                         "onEdit":{"fields":{},"intent":"demo.edit"},"expanded":false,
                         "onExpandedChange":{"fields":{},"intent":"demo.expand"}},"children":[
                         {"id":"beta.input","type":"SearchBarStateInputField","slot":"inputField",
                           "props":{
                           "onSearch":{"fields":{},"intent":"demo.expand"}}}]}]}}
                    """.trimIndent(),
                    actions,
                ),
            ).getOrThrow()

    private fun orphan(): ValidatedIr =
        IrParser()
            .parse(
                """
                {"version":"0.1.0","schemaVersion":"1.23.0",
                  "metadata":{"intents":{"demo.search":{"payload":{
                    "query":{"type":"string","required":true}}}}},
                 "root":{"id":"orphan","type":"SearchBarStateInputField","props":{
                   "onSearch":{"fields":{},"intent":"demo.search"}}}}
                """.trimIndent(),
            ).getOrThrow()
}
