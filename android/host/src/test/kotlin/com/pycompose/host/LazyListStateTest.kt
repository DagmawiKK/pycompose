package com.pycompose.host

import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.junit4.StateRestorationTester
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.performSemanticsAction
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

/** The lazy-list half of the state-projection protocol, end to end. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class LazyListStateTest {
    @get:Rule val compose = createComposeRule()

    @Test
    fun aDrivenIndexScrollsThereAndReportsTheSettledIndex() {
        // The holder's state parameter takes the drive; the item lands at the
        // top and the settled index reports back under its own field.
        val ir = mutableStateOf(parse(lazyColumn(firstVisibleIndex = "5")))
        val actions = mutableListOf<Action>()
        compose.setContent { PyComposeTheme { renderer(actions).Render(ir.value) } }

        compose.waitUntil(5000) { actions.isNotEmpty() }

        assertEquals(intent("demo.lazy"), actions[0].actionId)
        assertEquals(JsonPrimitive(5), actions[0].payload["firstVisibleIndex"])

        compose.runOnIdle { ir.value = parse(lazyColumn(firstVisibleIndex = "10")) }
        compose.waitForIdle()
        compose.waitUntil(5000) { actions.size == 2 }
        assertEquals(JsonPrimitive(10), actions[1].payload["firstVisibleIndex"])

        compose.runOnIdle { ir.value = parse(lazyColumn(firstVisibleIndex = "10")) }
        compose.waitForIdle()
        assertEquals(2, actions.size)
    }

    @Test
    fun anUndrivenListStaysAtTheTopAndSilent() {
        // Nothing stated: the holder starts at the first item and stays there.
        val ir = mutableStateOf(parse(lazyColumn(firstVisibleIndex = null)))
        val actions = mutableListOf<Action>()
        compose.setContent { PyComposeTheme { renderer(actions).Render(ir.value) } }

        compose.waitForIdle()

        assertTrue(actions.isEmpty())
    }

    @Test
    fun aUserScrollReportsOnlyItsSettledIndex() {
        val ir = parse(lazyColumn(firstVisibleIndex = null))
        val actions = mutableListOf<Action>()
        compose.setContent { PyComposeTheme { renderer(actions).Render(ir) } }
        compose.waitForIdle()
        assertTrue(actions.isEmpty())

        compose
            .onNode(SemanticsMatcher.keyIsDefined(SemanticsProperties.VerticalScrollAxisRange))
            .performTouchInput { swipeUp() }
        compose.waitForIdle()

        assertEquals(intent("demo.lazy"), actions.single().actionId)
        assertTrue(actions.single().payload["firstVisibleIndex"] != JsonPrimitive(0))
    }

    @Test
    fun scrollToTopClearsAPartiallyVisibleFirstItemsOffset() {
        val ir = mutableStateOf(parse(lazyColumn(firstVisibleIndex = "1")))
        val actions = mutableListOf<Action>()
        compose.setContent { PyComposeTheme { renderer(actions).Render(ir.value) } }
        compose.waitForIdle()
        val list =
            compose.onNode(
                SemanticsMatcher.keyIsDefined(SemanticsProperties.VerticalScrollAxisRange),
            )
        list.performSemanticsAction(SemanticsActions.ScrollToIndex) { it(0) }
        compose.waitForIdle()
        list.performSemanticsAction(SemanticsActions.ScrollBy) { it(0f, 10f) }
        compose.waitForIdle()
        val partial = list.fetchSemanticsNode().config[SemanticsProperties.VerticalScrollAxisRange]
        assertEquals(10f, partial.value())

        compose.runOnIdle { ir.value = parse(lazyColumn(firstVisibleIndex = "0")) }
        compose.waitForIdle()

        val top = list.fetchSemanticsNode().config[SemanticsProperties.VerticalScrollAxisRange]
        assertEquals(0f, top.value())
    }

    @Test
    fun restoringTheListDoesNotReapplyAnUnchangedDesiredIndex() {
        val restoration = StateRestorationTester(compose)
        val ir = parse(lazyColumn(firstVisibleIndex = "0"))
        val actions = mutableListOf<Action>()
        restoration.setContent { PyComposeTheme { renderer(actions).Render(ir) } }
        compose.waitForIdle()
        val list =
            compose.onNode(
                SemanticsMatcher.keyIsDefined(SemanticsProperties.VerticalScrollAxisRange),
            )
        list.performTouchInput { swipeUp() }
        compose.waitForIdle()
        val position =
            list
                .fetchSemanticsNode()
                .config[SemanticsProperties.VerticalScrollAxisRange]
                .value()
        assertTrue(position > 0f)
        compose.runOnIdle { actions.clear() }

        restoration.emulateSavedInstanceStateRestore()
        compose.waitForIdle()

        assertEquals(
            position,
            list.fetchSemanticsNode().config[SemanticsProperties.VerticalScrollAxisRange].value(),
        )
        assertTrue(actions.isEmpty())
    }

    private fun renderer(actions: MutableList<Action>): Renderer =
        Renderer(BuiltinComponents.registry(), ActionDispatcher { actions.add(it) })

    private fun parse(source: String): ValidatedIr = IrParser().parse(source).getOrThrow()

    private fun lazyColumn(firstVisibleIndex: String?): String {
        val stated =
            if (firstVisibleIndex != null) ",\"firstVisibleIndex\":$firstVisibleIndex" else ""
        val rows =
            (0 until 100).joinToString(",") { index ->
                """{"id":"root.t$index","type":"Text","props":{"text":"Row $index"}}"""
            }
        return """
            {"version":"0.1.0","schemaVersion":"1.23.0",
              "metadata":{"intents":{"demo.lazy":{"payload":{
                "firstVisibleIndex":{"required":true,"type":"integer"}}}}},
             "root":{"id":"root","type":"LazyColumn","props":{
               "onScrollIdle":{"fields":{},"intent":"demo.lazy"}$stated},
               "children":[$rows]}}
            """.trimIndent()
    }
}
