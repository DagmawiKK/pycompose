package com.pycompose.host.ui.holders

import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.longClick
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performTouchInput
import com.pycompose.host.ui.BuiltinComponents
import com.pycompose.host.ui.PyComposeTheme
import com.pycompose.host.ui.echoing
import com.pycompose.ir.IrParser
import com.pycompose.renderer.Action
import com.pycompose.renderer.ActionDispatcher
import com.pycompose.renderer.Renderer
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** Visibility drives, gesture echoes, timeout and stable-node lifetime. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34], application = android.app.Application::class)
class TooltipStateTest {
    @get:Rule val compose = createComposeRule()

    @Test
    fun changedVisibilityDrivesAndReportsBothTransitions() {
        val ir = mutableStateOf(parse(tooltip("false")))
        val actions = mutableListOf<Action>()
        val renderer = renderer(actions)
        compose.setContent { PyComposeTheme { renderer.Render(ir.value) } }
        compose.onNodeWithText("Hint").assertDoesNotExist()

        compose.runOnIdle { ir.value = parse(tooltip("true"), actions) }
        compose.onNodeWithText("Hint").assertExists()
        compose.runOnIdle { ir.value = parse(tooltip("false"), actions) }
        compose.onNodeWithText("Hint").assertDoesNotExist()

        assertEquals(listOf("""{"visible":true}""", """{"visible":false}"""), payloads(actions))
    }

    @Test
    fun timeoutReportsHiddenAndAnUnchangedDesireDoesNotReopenIt() {
        val ir = mutableStateOf(parse(tooltip("true", persistent = false)))
        val actions = mutableListOf<Action>()
        val renderer = renderer(actions)
        compose.setContent { PyComposeTheme { renderer.Render(ir.value) } }
        compose.onNodeWithText("Hint").assertExists()
        compose.mainClock.advanceTimeBy(3000)
        compose.onNodeWithText("Hint").assertDoesNotExist()

        compose.runOnIdle {
            ir.value =
                parse(tooltip("true", persistent = false, anchor = "Refreshed anchor"), actions)
        }
        compose.onNodeWithText("Refreshed anchor").assertExists()
        compose.onNodeWithText("Hint").assertDoesNotExist()
        assertEquals(listOf("""{"visible":true}""", """{"visible":false}"""), payloads(actions))
    }

    @Test
    fun aGestureEchoDoesNotRestartTheNativeTimeout() {
        val ir = mutableStateOf(parse(tooltip(null, persistent = false)))
        val actions = mutableListOf<Action>()
        val renderer = renderer(actions)
        compose.setContent { PyComposeTheme { renderer.Render(ir.value) } }
        compose.onNodeWithText("Anchor").performTouchInput { longClick() }
        compose.waitUntil(5000) { actions.isNotEmpty() }

        compose.runOnIdle { ir.value = parse(tooltip("true", persistent = false), actions) }
        compose.mainClock.advanceTimeBy(3000)
        compose.onNodeWithText("Hint").assertDoesNotExist()
        assertEquals(listOf("""{"visible":true}""", """{"visible":false}"""), payloads(actions))
    }

    private fun payloads(actions: List<Action>): List<String> =
        actions.map { it.payload.toString() }

    private fun renderer(actions: MutableList<Action>): Renderer =
        Renderer(BuiltinComponents.registry(), ActionDispatcher { actions.add(it) })

    private fun parse(
        source: String,
        actions: List<Action> = emptyList(),
    ) = IrParser().parse(echoing(source, actions)).getOrThrow()

    private fun tooltip(
        visible: String?,
        persistent: Boolean = true,
        anchor: String = "Anchor",
    ): String {
        val desired = visible?.let { "\"visible\":$it," } ?: ""
        return """
            {"version":"0.1.0","schemaVersion":"1.23.0",
              "metadata":{"intents":{"demo.visibility":{"payload":{
                "visible":{"required":true,"type":"boolean"}}}}},
             "root":{"id":"root","type":"TooltipBox","props":{
               $desired"isPersistent":$persistent,"onVisibilityChange":{"fields":{},
                 "intent":"demo.visibility"}},"children":[
               {"id":"anchor","type":"Text","props":{"text":"$anchor"}},
               {"id":"tooltip","type":"PlainTooltip","props":{},"slot":"tooltip","children":[
                 {"id":"body","type":"Text","props":{"text":"Hint"}}]}]}}
            """.trimIndent()
    }
}
