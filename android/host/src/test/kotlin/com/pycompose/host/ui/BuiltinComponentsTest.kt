package com.pycompose.host.ui

import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.test.ExperimentalTestApi
import androidx.compose.ui.test.getBoundsInRoot
import androidx.compose.ui.test.isToggleable
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithContentDescription
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performMouseInput
import androidx.compose.ui.test.performSemanticsAction
import androidx.test.core.app.ApplicationProvider
import com.pycompose.host.intent
import com.pycompose.host.resources.AndroidResources
import com.pycompose.host.resources.ResourceResolver
import com.pycompose.ir.IrParser
import com.pycompose.ir.generated.IrContract
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

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34], application = android.app.Application::class)
class BuiltinComponentsTest {
    @get:Rule val compose = createComposeRule()

    @Test fun nativeGoldenAndButtonDispatch() {
        assertEquals(IrContract.components.keys, BuiltinComponents.registry().types)
        val source = checkNotNull(javaClass.getResource("/component_screen.json")).readText()
        val snapshot = IrParser().parse(source).getOrThrow()
        val actions = mutableListOf<Action>()
        val renderer = Renderer(BuiltinComponents.registry(), ActionDispatcher { actions.add(it) })
        compose.setContent { PyComposeTheme { renderer.Render(snapshot) } }
        compose.onNodeWithText("Hello PyCompose").assertExists()
        compose.onNodeWithText("Ada").assertExists()
        compose.onNodeWithText("Add").performClick()
        assertEquals("increment", actions.single().actionId)
    }

    @Test
    fun boundControlsDispatchOnlyTheirOwnEventFieldsAndNestAListInAColumn() {
        val source =
            """
            {"version":"0.1.0","schemaVersion":"1.3.0",
              "metadata":{"intents":{"demo.toggle":{"payload":{
                "taskId":{"required":true,"type":"integer"},
                "done":{"required":true,"type":"boolean"}}}}},
             "root":{"id":"root","type":"Column","props":{},"children":[
               {"id":"row","type":"Row","props":{},"children":[
                 {"id":"row.box","type":"Checkbox","props":{
                   "checked":false,"onCheckedChange":{"fields":{"taskId":1},
                     "intent":"demo.toggle"}}},
                 {"id":"row.remove","type":"TextButton","props":{
                   "text":"Delete","onClick":{"fields":{"taskId":1},"intent":"demo.toggle"}}}]},
               {"id":"chip","type":"FilterChip","props":{
                 "label":"All","selected":true,"onClick":{"fields":{"taskId":1},
                   "intent":"demo.toggle"}}},
               {"id":"list","type":"LazyColumn","props":{},"children":[
                 {"id":"list.first","type":"Text","props":{"text":"First"}},
                 {"id":"list.second","type":"Text","props":{"text":"Second"}}]}]}}
            """.trimIndent()
        val snapshot = IrParser().parse(source).getOrThrow()
        val actions = mutableListOf<Action>()
        val renderer = Renderer(BuiltinComponents.registry(), ActionDispatcher { actions.add(it) })
        compose.setContent { PyComposeTheme { renderer.Render(snapshot) } }

        compose.onNodeWithText("First").assertExists()
        compose.onNodeWithText("Second").assertExists()
        compose.onNodeWithText("All").assertExists()
        compose.onNodeWithText("Delete").performClick()
        compose.onNodeWithText("All").performClick()
        val toggle = intent("demo.toggle", """{"taskId":1}""")
        assertEquals(listOf(toggle, toggle), actions.map { it.actionId })
        assertTrue(actions.all { it.payload.isEmpty() })
        compose.onNode(isToggleable()).performClick()
        assertEquals("""{"done":true}""", actions.last().payload.toString())
        assertEquals(3, actions.size)
    }

    @Test
    fun declaredSlotsComposeOnceAndThePrimaryChildrenBelowTheTopBar() {
        // Scaffold declares five content parameters; before slots the wire could
        // only say "children", so a topBar was unreachable from Python. The
        // failure mode this pins: slotted children leaking into the content
        // subtree and composing twice.
        val source =
            """
            {"version":"0.1.0","schemaVersion":"1.15.0","root":{
              "id":"root","type":"Scaffold","props":{},"children":[
                {"id":"body","type":"Text","props":{"text":"Content here"}},
                {"id":"bar","type":"Text","props":{"text":"Top bar"},"slot":"topBar"}]}}
            """.trimIndent()
        val snapshot = IrParser().parse(source).getOrThrow()
        val renderer = Renderer(BuiltinComponents.registry(), ActionDispatcher {})
        compose.setContent { PyComposeTheme { renderer.Render(snapshot) } }

        compose.onNodeWithText("Top bar").assertExists()
        assertEquals(1, compose.onAllNodesWithText("Top bar").fetchSemanticsNodes().size)
        assertEquals(1, compose.onAllNodesWithText("Content here").fetchSemanticsNodes().size)
        // The slot is laid out where Scaffold puts a top bar, and the content is
        // pushed below it by the PaddingValues its adapter consumes.
        val top =
            compose
                .onNodeWithText("Top bar")
                .getBoundsInRoot()
                .top.value
        val body =
            compose
                .onNodeWithText("Content here")
                .getBoundsInRoot()
                .top.value
        assertTrue("topBar at $top should precede content at $body", top < body)
    }

    @Test
    fun pressObservationReturnsAsActionsAndNeverDrivesAFrame() {
        // A Button naming an onPress action: the host creates the interaction
        // source, hands it to the component and reports the press transitions as
        // actions. The ripple stays Compose's own, so the app reacts a frame
        // later instead of driving the visual.
        val source =
            """
            {"version":"0.1.0","schemaVersion":"1.16.0",
              "metadata":{"intents":{"demo.click":{"payload":{}},"demo.press":{"payload":{
                "pressed":{"required":true,"type":"boolean"}}}}},
             "root":{"id":"root","type":"Column","props":{},"children":[
               {"id":"root.button","type":"Button","props":{
                 "text":"Tap","onClick":{"fields":{},"intent":"demo.click"},"onPress":{"fields":{},
                   "intent":"demo.press"}}}]}}
            """.trimIndent()
        val snapshot = IrParser().parse(source).getOrThrow()
        val actions = mutableListOf<Action>()
        val renderer = Renderer(BuiltinComponents.registry(), ActionDispatcher { actions.add(it) })
        compose.setContent { PyComposeTheme { renderer.Render(snapshot) } }

        compose.onNodeWithText("Tap").performClick()
        compose.waitUntil(5000) {
            actions.count { it.actionId == intent("demo.press") } == 2
        }
        assertEquals(
            listOf("""{"pressed":true}""", """{"pressed":false}"""),
            actions
                .filter { it.actionId == intent("demo.press") }
                .map { it.payload.toString() },
        )
        assertTrue(actions.any { it.actionId == intent("demo.click") })
    }

    @Test
    @OptIn(ExperimentalTestApi::class)
    fun focusAndHoverObservationsReturnAsActions() {
        // The same source reports focus and hover session state, so an app can
        // react to attention; the reaction a user sees still stays the
        // component's own and the app learns about it a frame later.
        val source =
            """
            {"version":"0.1.0","schemaVersion":"1.17.0",
              "metadata":{"intents":{"demo.click":{"payload":{}},"demo.focus":{"payload":{
                "focused":{"required":true,"type":"boolean"}}},"demo.hover":{"payload":{
                "hovered":{"required":true,"type":"boolean"}}}}},
             "root":{"id":"root","type":"Column","props":{},"children":[
               {"id":"root.button","type":"Button","props":{
                 "text":"Tap","onClick":{"fields":{},"intent":"demo.click"},
                 "onFocus":{"fields":{},"intent":"demo.focus"},"onHover":{"fields":{},
                   "intent":"demo.hover"}}}]}}
            """.trimIndent()
        val snapshot = IrParser().parse(source).getOrThrow()
        val actions = mutableListOf<Action>()
        val renderer = Renderer(BuiltinComponents.registry(), ActionDispatcher { actions.add(it) })
        compose.setContent { PyComposeTheme { renderer.Render(snapshot) } }

        compose.onNodeWithText("Tap").performSemanticsAction(SemanticsActions.RequestFocus)
        compose.waitUntil(5000) { actions.any { it.actionId == intent("demo.focus") } }
        assertEquals(
            """{"focused":true}""",
            actions.first { it.actionId == intent("demo.focus") }.payload.toString(),
        )

        compose.onNodeWithText("Tap").performMouseInput { moveTo(center) }
        compose.waitUntil(5000) { actions.any { it.actionId == intent("demo.hover") } }
        assertEquals(
            """{"hovered":true}""",
            actions.first { it.actionId == intent("demo.hover") }.payload.toString(),
        )
    }

    @Test fun resourceGoldenUsesRealLocalizedStringsDrawableAndAsset() {
        val source = checkNotNull(javaClass.getResource("/resource_screen.json")).readText()
        val context = ApplicationProvider.getApplicationContext<android.app.Application>()
        val resources = ResourceResolver(AndroidResources(context))
        val renderer = Renderer(BuiltinComponents.registry(resources), ActionDispatcher {})
        val ir = mutableStateOf(IrParser().parse(source).getOrThrow())
        compose.setContent { PyComposeTheme { renderer.Render(ir.value) } }
        val expected = "Bonjour depuis les ressources Android"
        compose.waitUntil(5000) {
            compose.onAllNodesWithText(expected).fetchSemanticsNodes().isNotEmpty() &&
                compose
                    .onAllNodesWithContentDescription("PyCompose logo")
                    .fetchSemanticsNodes()
                    .isNotEmpty() &&
                compose
                    .onAllNodesWithText("This text is loaded from an APK asset.\n")
                    .fetchSemanticsNodes()
                    .isNotEmpty()
        }
        compose.onNodeWithText(expected).assertExists()
        compose.onNodeWithContentDescription("PyCompose logo").assertExists()
        compose.onNodeWithText("This text is loaded from an APK asset.\n").assertExists()
        compose.runOnIdle {
            val plain = source.replace("\"resource\":\"@string/pycompose_greeting\",", "")
            ir.value = IrParser().parse(plain).getOrThrow()
        }
        compose.waitUntil(5000) {
            compose.onAllNodesWithText("Fallback").fetchSemanticsNodes().isNotEmpty()
        }
    }
}
