package com.pycompose.host

import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.junit4.StateRestorationTester
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.performTouchInput
import androidx.compose.ui.test.swipeUp
import com.pycompose.host.ui.BuiltinComponents
import com.pycompose.host.ui.PyComposeTheme
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

/** The scroll half of the state-projection protocol, end to end. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class ScrollStateTest {
    @get:Rule val compose = createComposeRule()

    @Test
    fun aColumnBehindTheGateScrollsThereAndReportsTheSettledOffset() {
        // The holder rides the modifier behind the app's boolean; a driven
        // offset settles like any scroll and reports the pixel it came to.
        val ir = mutableStateOf(parse(column(offset = "300.0", scrollable = true)))
        val actions = mutableListOf<Action>()
        compose.setContent { PyComposeTheme { renderer(actions).Render(ir.value) } }

        compose.waitUntil(5000) { actions.isNotEmpty() }

        assertEquals("app.demo.scroll.1", actions[0].actionId)
        assertEquals(JsonPrimitive(300), actions[0].payload["offset"])

        compose.runOnIdle { ir.value = parse(column(offset = "600.0", scrollable = true)) }
        compose.waitForIdle()
        compose.waitUntil(5000) { actions.size == 2 }
        assertEquals(JsonPrimitive(600), actions[1].payload["offset"])

        compose.runOnIdle { ir.value = parse(column(offset = "600.0", scrollable = true)) }
        compose.waitForIdle()
        assertEquals(2, actions.size)
    }

    @Test
    fun aColumnWithoutTheGateHasNoScrollSemantics() {
        // The holder is always created, but nothing attaches it: the column
        // stays the column it was, and an unstated gate means no scroll.
        val ir = mutableStateOf(parse(column(offset = null, scrollable = false)))
        val actions = mutableListOf<Action>()
        compose.setContent { PyComposeTheme { renderer(actions).Render(ir.value) } }

        compose.waitForIdle()

        assertTrue(actions.isEmpty())
        compose
            .onNode(SemanticsMatcher.keyIsDefined(SemanticsProperties.VerticalScrollAxisRange))
            .assertDoesNotExist()
    }

    @Test
    fun aUserScrollReportsOnlyItsSettledOffset() {
        val ir = parse(column(offset = null, scrollable = true))
        val actions = mutableListOf<Action>()
        compose.setContent { PyComposeTheme { renderer(actions).Render(ir) } }
        compose.waitForIdle()
        assertTrue(actions.isEmpty())

        compose
            .onNode(SemanticsMatcher.keyIsDefined(SemanticsProperties.VerticalScrollAxisRange))
            .performTouchInput { swipeUp() }
        compose.waitForIdle()

        assertEquals(actions.toString(), 1, actions.size)
        assertEquals("app.demo.scroll.1", actions.single().actionId)
        assertTrue(actions.single().payload["offset"] != JsonPrimitive(0))
    }

    @Test
    fun restoringTheScrollDoesNotReapplyAnUnchangedDesiredOffset() {
        val restoration = StateRestorationTester(compose)
        val ir = parse(column(offset = "0.0", scrollable = true))
        val actions = mutableListOf<Action>()
        restoration.setContent { PyComposeTheme { renderer(actions).Render(ir) } }
        compose.waitForIdle()
        val column =
            compose.onNode(
                SemanticsMatcher.keyIsDefined(SemanticsProperties.VerticalScrollAxisRange),
            )
        column.performTouchInput { swipeUp() }
        compose.waitForIdle()
        val position =
            column
                .fetchSemanticsNode()
                .config[SemanticsProperties.VerticalScrollAxisRange]
                .value()
        assertTrue(position > 0f)
        compose.runOnIdle { actions.clear() }

        restoration.emulateSavedInstanceStateRestore()
        compose.waitForIdle()

        assertEquals(
            position,
            column.fetchSemanticsNode().config[SemanticsProperties.VerticalScrollAxisRange].value(),
        )
        assertTrue(actions.isEmpty())
    }

    private fun renderer(actions: MutableList<Action>): Renderer =
        Renderer(BuiltinComponents.registry(), ActionDispatcher { actions.add(it) })

    private fun parse(source: String): ValidatedIr = IrParser().parse(source).getOrThrow()

    private fun column(
        offset: String?,
        scrollable: Boolean,
    ): String {
        val gate = if (scrollable) ",\"scrollable\":true" else ""
        val stated = if (offset != null) ",\"offset\":$offset" else ""
        val rows =
            (0 until 100).joinToString(",") { index ->
                """{"id":"root.t$index","type":"Text","props":{"text":"Row $index"}}"""
            }
        return """
            {"version":"0.1.0","schemaVersion":"1.23.0","metadata":{"actionBindings":{
              "app.demo.scroll.1":{"handlerId":"demo.scroll","payload":{
                "offset":{"required":true,"type":"number"}},"bound":{}}}},
             "root":{"id":"root","type":"Column","props":{
               "onScrollIdle":"app.demo.scroll.1"$stated$gate},
               "children":[$rows]}}
            """.trimIndent()
    }
}
