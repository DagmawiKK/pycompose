package com.pycompose.host.ui.holders

import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.junit4.StateRestorationTester
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.performTouchInput
import androidx.compose.ui.test.swipeDown
import androidx.compose.ui.test.swipeUp
import com.pycompose.host.intent
import com.pycompose.host.ui.BuiltinComponents
import com.pycompose.host.ui.PyComposeTheme
import com.pycompose.host.ui.echoing
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
        // The holder rides the modifier behind the app's boolean. It starts at
        // the first offset stated, which is no report; a new offset settles
        // like any scroll and reports the pixel it came to.
        val ir = mutableStateOf(parse(column(offset = 300, scrollable = true)))
        val actions = mutableListOf<Action>()
        compose.setContent { PyComposeTheme { renderer(actions).Render(ir.value) } }
        compose.waitForIdle()
        assertTrue(actions.isEmpty())

        compose.runOnIdle { ir.value = parse(column(offset = 600, scrollable = true)) }
        compose.waitForIdle()
        compose.waitUntil(5000) { actions.isNotEmpty() }
        assertEquals(intent("demo.scroll"), actions[0].actionId)
        assertEquals(JsonPrimitive(600), actions[0].payload["value"])

        compose.runOnIdle { ir.value = parse(column(offset = 600, scrollable = true)) }
        compose.waitForIdle()
        assertEquals(1, actions.size)
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
        assertEquals(intent("demo.scroll"), actions.single().actionId)
        assertTrue(actions.single().payload["value"] != JsonPrimitive(0))
    }

    @Test
    fun restoringTheScrollDoesNotReapplyAnUnchangedDesiredOffset() {
        val restoration = StateRestorationTester(compose)
        val ir = parse(column(offset = 0, scrollable = true))
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

    @Test
    fun aGestureInterruptsABoundTravelAndAStaleAnswerWaitsForTheReport() {
        // The app binds the offset to a slow tween; the user scrolls back mid-travel. The
        // travel yields to the gesture, the offset the user left is reported, and the app's
        // target restated before it has read that report does not pull the column back.
        val bound =
            """{"type":"binding","target":3000,"phase":"composition",
              "travel":{"kind":"tween","durationMs":4000,"delayMs":0}}"""
        val ir = mutableStateOf(parse(column(offset = 0, scrollable = true)))
        val actions = mutableListOf<Action>()
        val renderer = renderer(actions)
        compose.setContent { PyComposeTheme { renderer.Render(ir.value) } }
        compose.waitForIdle()

        compose.mainClock.autoAdvance = false
        ir.value = parse(column(offset = bound, scrollable = true))
        // Compose the binding with the clock held, then let a quarter of the travel run.
        compose.waitForIdle()
        repeat(4) { compose.mainClock.advanceTimeBy(250) }
        val travelling = offset()
        assertTrue("travelling: $travelling", travelling > 0f && travelling < 3000f)
        compose
            .onNode(SemanticsMatcher.keyIsDefined(SemanticsProperties.VerticalScrollAxisRange))
            .performTouchInput { swipeDown() }
        compose.mainClock.autoAdvance = true
        compose.waitForIdle()
        val left = offset()
        assertTrue("left: $left", left < travelling)
        assertEquals(actions.toString(), 1, actions.size)
        assertEquals(JsonPrimitive(left.toInt()), actions.single().payload["value"])

        // Stale: the same binding again, before the app has read the report.
        compose.runOnIdle { ir.value = parse(column(offset = bound, scrollable = true)) }
        compose.waitForIdle()
        assertEquals(left, offset())

        // The answer: the reported offset, echoed; nothing moves and nothing reports.
        compose.runOnIdle {
            ir.value = parse(column(offset = left.toInt(), scrollable = true), actions)
        }
        compose.waitForIdle()
        assertEquals(left, offset())
        assertEquals(1, actions.size)
    }

    private fun renderer(actions: MutableList<Action>): Renderer =
        Renderer(BuiltinComponents.registry(), ActionDispatcher { actions.add(it) })

    private fun parse(
        source: String,
        actions: List<Action> = emptyList(),
    ): ValidatedIr = IrParser().parse(echoing(source, actions)).getOrThrow()

    /** The offset the column is scrolled to, from its scroll semantics. */
    private fun offset(): Float =
        compose
            .onNode(SemanticsMatcher.keyIsDefined(SemanticsProperties.VerticalScrollAxisRange))
            .fetchSemanticsNode()
            .config[SemanticsProperties.VerticalScrollAxisRange]
            .value()

    private fun column(
        offset: Any?,
        scrollable: Boolean,
    ): String {
        val gate = if (scrollable) ",\"scrollable\":true" else ""
        val stated = if (offset != null) ",\"value\":$offset" else ""
        val rows =
            (0 until 100).joinToString(",") { index ->
                """{"id":"root.t$index","type":"Text","props":{"text":"Row $index"}}"""
            }
        return """
            {"version":"0.1.0","schemaVersion":"1.23.0",
              "metadata":{"intents":{"demo.scroll":{"payload":{
                "value":{"required":true,"type":"integer"}}}}},
             "root":{"id":"root","type":"Column","props":{
               "onValueSettled":{"fields":{},"intent":"demo.scroll"}$stated$gate},
               "children":[$rows]}}
            """.trimIndent()
    }
}
