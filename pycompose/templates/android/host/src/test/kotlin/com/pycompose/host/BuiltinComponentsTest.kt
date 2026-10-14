package com.pycompose.host

import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.isToggleable
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithContentDescription
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.test.core.app.ApplicationProvider
import com.pycompose.host.resources.AndroidResources
import com.pycompose.host.resources.ResourceResolver
import com.pycompose.host.ui.BuiltinComponents
import com.pycompose.host.ui.PyComposeTheme
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
            {"version":"0.1.0","schemaVersion":"1.3.0","metadata":{"actionBindings":{
              "app.demo.toggle.1":{"handlerId":"demo.toggle","bound":{"taskId":1},"payload":{
                "taskId":{"required":true,"type":"integer"},
                "done":{"required":true,"type":"boolean"}}}}},
             "root":{"id":"root","type":"Column","props":{},"children":[
               {"id":"row","type":"Row","props":{},"children":[
                 {"id":"row.box","type":"Checkbox","props":{
                   "checked":false,"onCheckedChange":"app.demo.toggle.1"}},
                 {"id":"row.remove","type":"TextButton","props":{
                   "text":"Delete","onClick":"app.demo.toggle.1"}}]},
               {"id":"chip","type":"FilterChip","props":{
                 "label":"All","selected":true,"onClick":"app.demo.toggle.1"}},
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
        assertEquals(listOf("app.demo.toggle.1", "app.demo.toggle.1"), actions.map { it.actionId })
        assertTrue(actions.all { it.payload.isEmpty() })
        compose.onNode(isToggleable()).performClick()
        assertEquals("""{"done":true}""", actions.last().payload.toString())
        assertEquals(3, actions.size)
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
