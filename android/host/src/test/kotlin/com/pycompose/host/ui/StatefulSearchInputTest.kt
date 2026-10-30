package com.pycompose.host.ui

import android.view.View
import android.view.ViewGroup
import android.view.inputmethod.EditorInfo
import android.view.inputmethod.InputConnection
import androidx.activity.ComponentActivity
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.assert
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.assertTextEquals
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performImeAction
import androidx.compose.ui.test.performTextInput
import androidx.compose.ui.test.performTextInputSelection
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.TextRange
import com.pycompose.host.intent
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

/** State-based input, observed through native editing semantics and typed actions. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34], application = android.app.Application::class)
class StatefulSearchInputTest {
    @get:Rule val compose = createAndroidComposeRule<ComponentActivity>()
    private val actions = mutableListOf<Action>()
    private val diagnostics = mutableListOf<String>()
    private val renderer =
        Renderer(
            BuiltinComponents.registry(),
            ActionDispatcher {
                actions.add(it)
            },
            report = diagnostics::add,
        )

    @Test
    fun selectionOnlyEditsReportTheCompleteEditingValue() {
        compose.setContent { PyComposeTheme { renderer.Render(snapshot()) } }
        val field = compose.onNode(hasSetTextAction())
        field.assertTextEquals("compose")
        field.performTextInputSelection(TextRange(2, 5))

        compose.waitUntil(5000) { edits().isNotEmpty() }
        val payload = edits().last().payload
        assertEquals(JsonPrimitive("compose"), payload["text"])
        assertEquals(JsonPrimitive(2), payload["selectionStart"])
        assertEquals(JsonPrimitive(5), payload["selectionEnd"])
        assertEquals(JsonPrimitive(1), payload["revision"])
    }

    @Test
    fun staleEchoesDoNotUndoNewerTypingAndAcknowledgementsDoNotReportAgain() {
        val current = mutableStateOf(snapshot())
        compose.setContent { PyComposeTheme { renderer.Render(current.value) } }
        val field = compose.onNode(hasSetTextAction())
        field.performTextInput("x")
        compose.waitUntil(5000) { edits().size == 1 }
        field.performTextInput("y")
        compose.waitUntil(5000) { edits().size == 2 }
        compose.runOnIdle { current.value = snapshot(Edit("composex", 8, 8, 1)) }
        field.assertTextEquals("composexy")
        assertEquals(
            TextRange(9),
            field.fetchSemanticsNode().config[SemanticsProperties.TextSelectionRange],
        )
        compose.runOnIdle { current.value = snapshot(Edit("composexy", 9, 9, 2)) }
        compose.waitForIdle()
        assertEquals(2, edits().size)
        field.assertTextEquals("composexy")
    }

    @Test
    fun anAcknowledgementCannotOverwriteAnEditPendingObservation() {
        val current = mutableStateOf(snapshot())
        var pending: (() -> Unit)? = null
        compose.setContent {
            val ir = current.value
            SideEffect {
                pending?.let {
                    pending = null
                    it()
                }
            }
            PyComposeTheme { renderer.Render(ir) }
        }
        val field = compose.onNode(hasSetTextAction())
        field.performTextInput("x")
        compose.waitUntil(5000) { edits().size == 1 }
        val insert = field.fetchSemanticsNode().config[SemanticsActions.InsertTextAtCursor].action!!
        compose.runOnIdle {
            pending = { insert(AnnotatedString("y")) }
            current.value = snapshot(Edit("composex", 8, 8, 1))
        }
        field.assertTextEquals("composexy")
        compose.waitUntil(5000) { edits().size == 2 }
        assertEquals(JsonPrimitive(2), edits().last().payload["revision"])
    }

    @Test
    fun newerAppCommandsReplaceTextAndClampReversedSelectionWithoutEchoReports() {
        val current = mutableStateOf(snapshot())
        compose.setContent { PyComposeTheme { renderer.Render(current.value) } }
        val field = compose.onNode(hasSetTextAction())
        field.performTextInput("x")
        compose.waitUntil(5000) { edits().size == 1 }
        compose.runOnIdle { current.value = snapshot(Edit("new", 100, 1, 5)) }
        field.assertTextEquals("new")
        assertEquals(
            TextRange(3, 1),
            field.fetchSemanticsNode().config[SemanticsProperties.TextSelectionRange],
        )
        assertEquals(1, edits().size)
        field.performTextInput("!")
        compose.waitUntil(5000) { edits().size == 2 }
        assertEquals(JsonPrimitive("n!"), edits().last().payload["text"])
        assertEquals(JsonPrimitive(6), edits().last().payload["revision"])
    }

    @Test
    fun searchAndExpansionCallbacksUseNativeBehaviorAndTypedPayloads() {
        compose.setContent {
            PyComposeTheme { renderer.Render(snapshot(options = Options(expanded = false))) }
        }
        val field = compose.onNode(hasSetTextAction())
        field.performClick()
        compose.waitUntil(5000) { actions.any { it.actionId == intent("demo.expand") } }
        assertEquals(
            JsonPrimitive(true),
            actions
                .last {
                    it.actionId == intent("demo.expand")
                }.payload["expanded"],
        )
        field.performImeAction()
        compose.waitUntil(5000) { actions.any { it.actionId == intent("demo.search") } }
        assertEquals(
            JsonPrimitive("compose"),
            actions
                .last {
                    it.actionId == intent("demo.search")
                }.payload["query"],
        )
        assertEquals(0, edits().size)
    }

    @Test
    fun readOnlyRejectsEditingAndNamedSlotsRender() {
        compose.setContent {
            PyComposeTheme {
                renderer.Render(
                    snapshot(options = Options(readOnly = true, slots = true)),
                )
            }
        }
        compose.onNodeWithText("Prefix").assertIsDisplayed()
        compose.onNodeWithText("Suffix").assertIsDisplayed()
        compose.onNodeWithText("compose", useUnmergedTree = true).assert(hasSetTextAction().not())
        compose.waitForIdle()
        assertEquals(0, edits().size)
    }

    @Test
    fun disabledFieldCannotBeEdited() {
        compose.setContent {
            PyComposeTheme { renderer.Render(snapshot(options = Options(enabled = false))) }
        }
        compose.onNodeWithText("compose").assertIsNotEnabled().assert(hasSetTextAction().not())
        assertEquals(0, edits().size)
    }

    private fun edits(): List<Action> = actions.filter { it.actionId == intent("demo.edit") }

    @Test
    fun acknowledgingAnEditPreservesNativeImeComposition() {
        val current = mutableStateOf(snapshot())
        compose.setContent { PyComposeTheme { renderer.Render(current.value) } }
        val field = compose.onNode(hasSetTextAction())
        field.performClick()
        lateinit var connection: InputConnection
        compose.runOnIdle {
            connection = checkNotNull(inputConnection(compose.activity.window.decorView))
            connection.setComposingText("x", 1)
        }
        compose.waitUntil(5000) { edits().size == 1 }
        assertEquals(
            TextRange(7, 8),
            field.fetchSemanticsNode().config[SemanticsProperties.TextCompositionRange],
        )
        compose.runOnIdle { current.value = snapshot(Edit("composex", 8, 8, 1)) }
        assertEquals(
            TextRange(7, 8),
            field.fetchSemanticsNode().config[SemanticsProperties.TextCompositionRange],
        )
        assertEquals(1, edits().size)
    }

    private fun inputConnection(view: View): InputConnection? =
        view.onCreateInputConnection(EditorInfo()) ?: (view as? ViewGroup)?.let { group ->
            (0 until group.childCount).firstNotNullOfOrNull {
                inputConnection(
                    group.getChildAt(it),
                )
            }
        }

    @Test
    fun equalRevisionCanNormalizeAndNewIdentityStartsFromItsSnapshot() {
        val current = mutableStateOf(snapshot())
        compose.setContent { PyComposeTheme { renderer.Render(current.value) } }
        val field = compose.onNode(hasSetTextAction())
        field.performTextInput("x")
        compose.waitUntil(5000) { edits().size == 1 }
        compose.runOnIdle { current.value = snapshot(Edit("normalized", 2, 2, 1)) }
        field.assertTextEquals("normalized")
        assertEquals(1, edits().size)
        compose.runOnIdle { current.value = snapshot(Edit("fresh", 5, 5, 0), id = "new-field") }
        field.assertTextEquals("fresh")
        field.performClick()
        compose.waitForIdle()
        compose.runOnIdle { actions.clear() }
        field.performTextInput("!")
        compose.waitForIdle()
        assertEquals("actions=$actions diagnostics=$diagnostics", 1, edits().size)
        assertEquals(JsonPrimitive(1), edits().last().payload["revision"])
        assertEquals(JsonPrimitive("fresh!"), edits().last().payload["text"])
    }

    @Test
    fun exhaustedRevisionsNeverWrapAndFurtherNativeEditsAreRejected() {
        val current = mutableStateOf(snapshot(Edit(revision = Long.MAX_VALUE - 1)))
        compose.setContent { PyComposeTheme { renderer.Render(current.value) } }
        val field = compose.onNode(hasSetTextAction())
        field.performTextInput("x")
        compose.waitUntil(5000) { edits().size == 1 }
        assertEquals(JsonPrimitive(Long.MAX_VALUE), edits().last().payload["revision"])
        compose.runOnIdle { current.value = snapshot(Edit("composex", 8, 8, Long.MAX_VALUE)) }
        field.performTextInput("y")
        field.assertTextEquals("composex")
        assertEquals(1, edits().size)
        assertEquals(1, diagnostics.size)
    }

    @Test
    fun anIncompatibleAtomicBindingIsDiagnosedInsteadOfDispatchingInvalidData() {
        compose.setContent {
            PyComposeTheme { renderer.Render(snapshot(options = Options(revisionType = "string"))) }
        }
        compose.onNode(hasSetTextAction()).performTextInput("x")
        compose.waitForIdle()
        assertEquals(0, edits().size)
        assertEquals(1, diagnostics.size)
    }

    private data class Options(
        val expanded: Boolean = true,
        val readOnly: Boolean = false,
        val enabled: Boolean = true,
        val slots: Boolean = false,
        val revisionType: String = "integer",
    )

    private data class Edit(
        val text: String = "compose",
        val start: Int = 7,
        val end: Int = 7,
        val revision: Long = 0,
    )

    private fun snapshot(
        edit: Edit = Edit(),
        options: Options = Options(),
        id: String = "field",
    ): ValidatedIr {
        val children =
            if (options.slots) {
                """{"id":"prefix","type":"Text","slot":"prefix","props":{"text":"Prefix"}},
            {"id":"suffix","type":"Text","slot":"suffix","props":{"text":"Suffix"}}"""
            } else {
                ""
            }
        return IrParser()
            .parse(
                """
                {"version":"0.1.0","schemaVersion":"1.23.0",
                  "metadata":{"intents":{"demo.edit":{"payload":{
                    "text":{"type":"string","required":true},
                    "selectionStart":{"type":"integer","required":true},
                    "selectionEnd":{"type":"integer","required":true},
                     "revision":{"type":"${options.revisionType}","required":true}}},
                       "demo.search":{"payload":{
                    "query":{"type":"string","required":true}}},"demo.expand":{"payload":{
                    "expanded":{"type":"boolean","required":true}}}}},
                 "root":{"id":"$id","type":"StatefulSearchBarInputField","props":{
                   "text":"${edit.text}","selectionStart":${edit.start},
                   "selectionEnd":${edit.end},"revision":${edit.revision},
                   "onEdit":{"fields":{},"intent":"demo.edit"},"onSearch":{"fields":{},
                     "intent":"demo.search"},
                    "expanded":${options.expanded},"readOnly":${options.readOnly},
                      "enabled":${options.enabled},
                   "onExpandedChange":{"fields":{},"intent":"demo.expand"}},"children":[
                    $children]}}
                """.trimIndent(),
            ).getOrThrow()
    }
}
