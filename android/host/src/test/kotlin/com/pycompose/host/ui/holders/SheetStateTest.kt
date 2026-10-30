package com.pycompose.host.ui.holders

import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.performSemanticsAction
import com.pycompose.host.ui.BuiltinComponents
import com.pycompose.host.ui.PyComposeTheme
import com.pycompose.ir.IrParser
import com.pycompose.ir.ValidatedIr
import com.pycompose.renderer.Action
import com.pycompose.renderer.ActionDispatcher
import com.pycompose.renderer.Renderer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** The state-projection protocol for a component that shows itself once composed. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34], application = android.app.Application::class)
class SheetStateTest {
    @get:Rule val compose = createComposeRule()

    @Test
    fun theHostShowsTheSheetAndReportsEverySettledChange() {
        // Composing the sheet is the drive: the component shows itself, settles,
        // and reports. Closing is the host's hide, and it reports too.
        val ir = mutableStateOf(parse(sheet(open = "true")))
        val actions = mutableListOf<Action>()
        compose.setContent { PyComposeTheme { renderer(actions).Render(ir.value) } }

        compose.waitUntil(5000) { actions.isNotEmpty() }
        assertEquals("""{"open":true}""", actions[0].payload.toString())
        assertTrue(sheetBodyIsComposed())

        compose.runOnIdle { ir.value = parse(sheet(open = "false")) }
        compose.waitForIdle()
        compose.waitUntil(5000) { actions.size == 2 }
        assertEquals("""{"open":false}""", actions[1].payload.toString())
        compose.waitUntil(5000) { !sheetBodyIsComposed() }
    }

    @Test
    fun aSheetClosedByTheAppCanBeShownAgain() {
        // Presence follows the app: a sheet that settled hidden leaves the tree,
        // and a later change of the desired value brings it back with the state
        // the host still owns.
        val ir = mutableStateOf(parse(sheet(open = "true")))
        val actions = mutableListOf<Action>()
        compose.setContent { PyComposeTheme { renderer(actions).Render(ir.value) } }
        compose.waitUntil(5000) { actions.size == 1 }

        compose.runOnIdle { ir.value = parse(sheet(open = "false")) }
        compose.waitForIdle()
        compose.waitUntil(5000) { actions.size == 2 }

        compose.runOnIdle { ir.value = parse(sheet(open = "true")) }
        compose.waitForIdle()
        compose.waitUntil(5000) { actions.size == 3 }
        assertEquals("""{"open":true}""", actions[2].payload.toString())
        assertTrue(sheetBodyIsComposed())
    }

    @Test
    fun aDismissedSheetReportsTheGestureAndIsNotForcedBackOpen() {
        // The user dismissing the sheet is the report's whole reason to exist:
        // the app still desires it open, and the host must not fight the gesture
        // by re-showing it on the next snapshot. The handle carries the dismiss
        // action the native component offers, and nothing answers it.
        val ir = mutableStateOf(parse(sheet(open = "true", handle = true)))
        val actions = mutableListOf<Action>()
        compose.setContent { PyComposeTheme { renderer(actions).Render(ir.value) } }
        compose.waitUntil(5000) { actions.size == 1 }

        compose
            .onNode(SemanticsMatcher.keyIsDefined(SemanticsActions.Dismiss))
            .performSemanticsAction(SemanticsActions.Dismiss)
        compose.waitUntil(5000) { actions.size == 2 }

        assertEquals("""{"open":false}""", actions[1].payload.toString())
        compose.waitUntil(5000) { !sheetBodyIsComposed() }
    }

    @Test
    fun aSheetNobodyReportsOnStaysSilentWithoutAReport() {
        // Reporting is opt-in and about changes: a sheet the app does not listen
        // to still shows, and nothing reaches the dispatcher.
        val ir = mutableStateOf(parse(sheet(open = "true", report = false)))
        val actions = mutableListOf<Action>()
        compose.setContent { PyComposeTheme { renderer(actions).Render(ir.value) } }

        compose.waitUntil(5000) { sheetBodyIsComposed() }
        compose.waitForIdle()
        assertTrue(actions.isEmpty())
    }

    @Test
    fun aRepeatedSnapshotKeepsTheSheetAndReportsNothing() {
        // Pulling a snapshot twice must not recreate state a gesture is moving,
        // and must not replay a report the app already handled.
        val source = sheet(open = "true")
        val ir = mutableStateOf(parse(source))
        val actions = mutableListOf<Action>()
        compose.setContent { PyComposeTheme { renderer(actions).Render(ir.value) } }
        compose.waitUntil(5000) { actions.size == 1 }

        compose.runOnIdle { ir.value = parse(source) }
        compose.waitForIdle()

        assertEquals(1, actions.size)
        assertTrue(sheetBodyIsComposed())
    }

    @Test
    fun aSheetTheAppSaysItDoesNotWantIsNotComposedAtAll() {
        // Presence is the host's to decide, and false is a decision. A composed
        // sheet would show itself and then sit in front of the app, hidden.
        val ir = mutableStateOf(parse(sheet(open = "false")))
        val actions = mutableListOf<Action>()
        compose.setContent { PyComposeTheme { renderer(actions).Render(ir.value) } }
        compose.waitForIdle()

        assertTrue(actions.isEmpty())
        assertTrue(!sheetBodyIsComposed())
    }

    @Test
    fun anUndrivenSheetIsNotComposedAndStaysSilent() {
        // Neither half declared: the host holds the state, and nothing asks for
        // the sheet to be on screen.
        val ir = mutableStateOf(parse(sheet(open = null)))
        val actions = mutableListOf<Action>()
        compose.setContent { PyComposeTheme { renderer(actions).Render(ir.value) } }
        compose.waitForIdle()

        assertTrue(actions.isEmpty())
        assertTrue(!sheetBodyIsComposed())
    }

    /** Whether the sheet's own content is in the tree at all. */
    private fun sheetBodyIsComposed(): Boolean =
        compose.onAllNodesWithText("Sheet body").fetchSemanticsNodes().isNotEmpty()

    private fun renderer(actions: MutableList<Action>): Renderer =
        Renderer(BuiltinComponents.registry(), ActionDispatcher { actions.add(it) })

    private fun parse(source: String): ValidatedIr = IrParser().parse(source).getOrThrow()

    private fun sheet(
        open: String?,
        report: Boolean = true,
        handle: Boolean = false,
    ): String {
        val props = mutableListOf<String>()
        if (open != null) {
            props.add("\"open\":$open")
        }
        if (report) {
            props.add("\"onOpenChange\":{\"fields\":{},\"intent\":\"demo.sheet\"}")
        }
        val children =
            mutableListOf(
                """{"id":"sheet.body","type":"Text","props":{"text":"Sheet body"}}""",
            )
        if (handle) {
            children.add(
                """{"id":"sheet.handle","type":"Text",""" +
                    """"props":{"text":"Handle"},"slot":"dragHandle"}""",
            )
        }
        return """
            {"version":"0.1.0","schemaVersion":"1.19.0",
              "metadata":{"intents":{"demo.sheet":{"payload":{
                "open":{"required":true,"type":"boolean"}}}}},
             "root":{"id":"root","type":"ModalBottomSheet","props":{
               ${props.joinToString(",")}
             },
               "children":[${children.joinToString(",")}]}}
            """.trimIndent()
    }
}
