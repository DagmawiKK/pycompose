package com.pycompose.host

import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.getBoundsInRoot
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performSemanticsAction
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
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

/** The state-projection protocol, end to end through the registered drawer adapter. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34], application = android.app.Application::class)
class DrawerStateTest {
    @get:Rule val compose = createComposeRule()

    @Test
    fun theHostDrivesTheDrawerAndReportsEverySettledChange() {
        // The app states the desired value; the host owns the DrawerState,
        // drives it towards that value, and reports what it settled on. The
        // report is how the app learns about a change it did not cause.
        val ir = mutableStateOf(parse(drawer(open = "true")))
        val actions = mutableListOf<Action>()
        compose.setContent { PyComposeTheme { renderer(actions).Render(ir.value) } }
        compose.waitForIdle()

        assertEquals(0.dp, panelLeft())
        compose.waitUntil(5000) { actions.isNotEmpty() }
        assertEquals("""{"open":true}""", actions[0].payload.toString())

        compose.runOnIdle { ir.value = parse(drawer(open = "false")) }
        compose.waitForIdle()
        assertEquals(2, actions.size)
        assertEquals("""{"open":false}""", actions[1].payload.toString())
        assertTrue(panelLeft() < 0.dp)
    }

    @Test
    fun aDismissedDrawerReportsTheGestureAndIsNotForcedBackOpen() {
        // The user moving the drawer is the report's whole reason to exist:
        // the app still desires open, and the host must not fight the gesture
        // by re-opening on the next snapshot.
        val ir = mutableStateOf(parse(drawer(open = "true")))
        val actions = mutableListOf<Action>()
        compose.setContent { PyComposeTheme { renderer(actions).Render(ir.value) } }
        compose.waitUntil(5000) { actions.isNotEmpty() }

        compose
            .onNode(SemanticsMatcher.keyIsDefined(SemanticsActions.Dismiss))
            .performSemanticsAction(SemanticsActions.Dismiss)
        compose.waitUntil(5000) { actions.size == 2 }

        assertEquals("""{"open":false}""", actions[1].payload.toString())
        compose.waitForIdle()
        assertTrue(panelLeft() < 0.dp)
    }

    @Test
    fun aDrawerNobodyReportsOnStaysSilentWithoutAReport() {
        // Reporting is opt-in and about changes: a drawer the app does not
        // listen to still works, and nothing reaches the dispatcher.
        val ir = mutableStateOf(parse(drawer(open = "true", report = false)))
        val actions = mutableListOf<Action>()
        compose.setContent { PyComposeTheme { renderer(actions).Render(ir.value) } }
        compose.waitForIdle()

        assertTrue(actions.isEmpty())
        assertEquals(0.dp, panelLeft())
    }

    @Test
    fun aRepeatedSnapshotKeepsTheDrawerAndReportsNothing() {
        // Pulling a snapshot twice must not recreate state a gesture is
        // moving, and must not replay a report the app already handled.
        val source = drawer(open = "true")
        val ir = mutableStateOf(parse(source))
        val actions = mutableListOf<Action>()
        compose.setContent { PyComposeTheme { renderer(actions).Render(ir.value) } }
        compose.waitUntil(5000) { actions.isNotEmpty() }

        compose.runOnIdle { ir.value = parse(source) }
        compose.waitForIdle()

        assertEquals(1, actions.size)
        assertEquals(0.dp, panelLeft())
    }

    @Test
    fun anUndrivenDrawerStaysClosedAndSilent() {
        // Neither half declared: the host holds the state for gestures only.
        val ir = mutableStateOf(parse(drawer(open = null)))
        val actions = mutableListOf<Action>()
        compose.setContent { PyComposeTheme { renderer(actions).Render(ir.value) } }

        compose.waitForIdle()
        assertTrue(actions.isEmpty())
        assertTrue(panelLeft() < 0.dp)
    }

    /** The left edge of the drawer panel: 0 when open, off-screen when closed. */
    private fun panelLeft(): Dp = compose.onNodeWithText("Home").getBoundsInRoot().left

    private fun renderer(actions: MutableList<Action>): Renderer =
        Renderer(BuiltinComponents.registry(), ActionDispatcher { actions.add(it) })

    private fun parse(source: String): ValidatedIr = IrParser().parse(source).getOrThrow()

    private fun drawer(
        open: String?,
        report: Boolean = true,
    ): String {
        val props = mutableListOf<String>()
        if (open != null) {
            props.add("\"open\":$open")
        }
        if (report) {
            props.add("\"onOpenChange\":\"app.demo.drawer.1\"")
        }
        return """
            {"version":"0.1.0","schemaVersion":"1.18.0","metadata":{"actionBindings":{
              "app.demo.drawer.1":{"handlerId":"demo.drawer","payload":{
                "open":{"required":true,"type":"boolean"}},"bound":{}}}},
             "root":{"id":"root","type":"ModalNavigationDrawer","props":{
               ${props.joinToString(",")}
             },
               "children":[
                 {"id":"root.body","type":"Text","props":{"text":"Body"}},
                 {"id":"root.panel","type":"Text","props":{"text":"Home"},"slot":"drawer"}]}}
            """.trimIndent()
    }
}
