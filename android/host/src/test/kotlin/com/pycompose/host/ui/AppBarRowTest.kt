package com.pycompose.host.ui

import androidx.activity.ComponentActivity
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.performClick
import com.pycompose.host.intent
import com.pycompose.ir.IrParser
import com.pycompose.ir.ValidatedIr
import com.pycompose.renderer.Action
import com.pycompose.renderer.ActionDispatcher
import com.pycompose.renderer.Renderer
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/**
 * A bar built from item components: each child is applied to the bar's builder, and the
 * overflow menu the bar hands its indicator opens when the app states it and reports a
 * dismissal the menu makes itself.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class AppBarRowTest {
    @get:Rule val compose = createAndroidComposeRule<ComponentActivity>()

    private val actions = mutableListOf<Action>()

    @Test
    fun eachChildIsAnItemOfTheBar() {
        render(mutableStateOf(snapshot(expanded = null)))

        compose.onNode(hasText("A"), useUnmergedTree = true).assertExists()
        compose.onNode(hasText("Overflow"), useUnmergedTree = true).assertExists()
    }

    @Test
    fun theMenuOpensWhenTheAppExpandsIt() {
        val ir = mutableStateOf(snapshot(expanded = false))
        render(ir)
        compose.onNode(hasText("Third")).assertDoesNotExist()

        compose.runOnIdle { ir.value = snapshot(expanded = true) }
        compose.waitForIdle()

        compose.onNode(hasText("Third")).assertExists()
    }

    @Test
    fun choosingAMenuItemRunsItAndReportsTheDismissal() {
        render(mutableStateOf(snapshot(expanded = true)))

        compose.onNode(hasText("Third")).performClick()
        compose.waitForIdle()

        assertTrue(actions.any { it.actionId == intent("demo.third") })
        // A drive reports where it left the holder, as every property holder does: the
        // app's own true comes back first, then the menu's dismissal, once.
        val reports = actions.filter { it.actionId == intent("demo.expanded") }
        assertEquals(
            listOf(JsonPrimitive(true), JsonPrimitive(false)),
            reports.map { it.payload["isExpanded"] },
        )
        compose.onNode(hasText("Third")).assertDoesNotExist()
    }

    private fun render(ir: androidx.compose.runtime.State<ValidatedIr>) {
        val renderer = Renderer(BuiltinComponents.registry(), ActionDispatcher { actions.add(it) })
        compose.setContent { PyComposeTheme { renderer.Render(ir.value) } }
        compose.waitForIdle()
    }

    private fun item(
        id: String,
        label: String,
    ): String =
        """{"id":"$id","type":"AppBarClickableItem","props":{"label":"$label",
             "onClick":{"fields":{},"intent":"demo.$id"}},"children":[
             {"id":"$id.icon","type":"Text","slot":"icon","props":{"text":"${label.first()}"}}]}"""

    private fun snapshot(expanded: Boolean?): ValidatedIr {
        val stated = expanded?.let { "\"isExpanded\":$it," } ?: ""
        return IrParser()
            .parse(
                """
                {"version":"0.1.0","schemaVersion":"1.23.0",
                  "metadata":{"intents":{"demo.first":{"payload":{}},
                    "demo.second":{"payload":{}},"demo.third":{"payload":{}},
                    "demo.expanded":{"payload":{
                      "isExpanded":{"type":"boolean","required":true}}}}},
                 "root":{"id":"bar","type":"AppBarRow","props":{$stated
                   "modifier":{"operations":[{"type":"width","width":120}]},
                   "onIsExpandedChange":{"fields":{},"intent":"demo.expanded"}},"children":[
                   {"id":"more","type":"Text","slot":"overflowIndicator",
                     "props":{"text":"Overflow"}},
                   ${item("first", "A")},${item("second", "Second")},${item("third", "Third")}]}}
                """.trimIndent(),
            ).getOrThrow()
    }
}
