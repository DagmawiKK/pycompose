package com.pycompose.host.ui.holders

import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.getBoundsInRoot
import androidx.compose.ui.test.junit4.StateRestorationTester
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performSemanticsAction
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.pycompose.host.ui.BuiltinComponents
import com.pycompose.host.ui.PyComposeTheme
import com.pycompose.host.ui.echoing
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
    fun aRotationKeepsTheDrawerTheUserMovedWhileTheAppStillStatesTheOldValue() {
        // The app ignores the user's dismissal and keeps stating "open". Across a
        // rotation that is not a new statement, so the user's gesture stands.
        val actions = mutableListOf<Action>()
        val ir = mutableStateOf(parse(drawer(open = "true")))
        val restoration = restored(ir, actions)
        compose.waitUntil(5000) { actions.size == 1 }
        compose
            .onNode(SemanticsMatcher.keyIsDefined(SemanticsActions.Dismiss))
            .performSemanticsAction(SemanticsActions.Dismiss)
        compose.waitUntil(5000) { actions.size == 2 }
        compose.runOnIdle { ir.value = parse(drawer(open = "true"), actions) }

        restoration.emulateSavedInstanceStateRestore()
        compose.waitForIdle()

        assertTrue(panelLeft() < 0.dp)
        assertEquals(2, actions.size)
    }

    @Test
    fun aRestoredAppStatingADifferentValueDrivesTheDrawerToIt() {
        // After process death the app restores its own data; a value different
        // from its last statement is a new statement, and it wins.
        val actions = mutableListOf<Action>()
        val ir = mutableStateOf(parse(drawer(open = "true")))
        val restoration = restored(ir, actions)
        compose.waitUntil(5000) { actions.size == 1 }
        compose.runOnIdle { ir.value = parse(drawer(open = "false"), actions) }

        restoration.emulateSavedInstanceStateRestore()
        compose.waitUntil(5000) { actions.size == 2 }

        assertEquals("""{"open":false}""", actions[1].payload.toString())
        assertTrue(panelLeft() < 0.dp)
    }

    /** Content whose renderer is recreated on restore, as MainActivity remembers it. */
    private fun restored(
        ir: androidx.compose.runtime.State<ValidatedIr>,
        actions: MutableList<Action>,
    ): StateRestorationTester {
        val restoration = StateRestorationTester(compose)
        restoration.setContent {
            val renderer = remember { renderer(actions) }
            PyComposeTheme { renderer.Render(ir.value) }
        }
        return restoration
    }

    /** The left edge of the drawer panel: 0 when open, off-screen when closed. */
    private fun panelLeft(): Dp = compose.onNodeWithText("Home").getBoundsInRoot().left

    private fun renderer(actions: MutableList<Action>): Renderer =
        Renderer(BuiltinComponents.registry(), ActionDispatcher { actions.add(it) })

    private fun parse(
        source: String,
        actions: List<Action> = emptyList(),
    ): ValidatedIr = IrParser().parse(echoing(source, actions)).getOrThrow()

    private fun drawer(
        open: String?,
        report: Boolean = true,
    ): String {
        val props = mutableListOf<String>()
        if (open != null) {
            props.add("\"open\":$open")
        }
        if (report) {
            props.add("\"onOpenChange\":{\"fields\":{},\"intent\":\"demo.drawer\"}")
        }
        return """
            {"version":"0.1.0","schemaVersion":"1.18.0",
              "metadata":{"intents":{"demo.drawer":{"payload":{
                "open":{"required":true,"type":"boolean"}}}}},
             "root":{"id":"root","type":"ModalNavigationDrawer","props":{
               ${props.joinToString(",")}
             },
               "children":[
                 {"id":"root.body","type":"Text","props":{"text":"Body"}},
                 {"id":"root.panel","type":"Text","props":{"text":"Home"},"slot":"drawer"}]}}
            """.trimIndent()
    }
}
