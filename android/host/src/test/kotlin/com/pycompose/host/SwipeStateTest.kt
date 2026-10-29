package com.pycompose.host

import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.getBoundsInRoot
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.performTouchInput
import androidx.compose.ui.test.swipeLeft
import androidx.compose.ui.test.swipeRight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.pycompose.host.ui.BuiltinComponents
import com.pycompose.host.ui.PyComposeTheme
import com.pycompose.ir.IrParser
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

/** The state-projection protocol for the three-anchor swipe holder. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34], application = android.app.Application::class)
class SwipeStateTest {
    @get:Rule val compose = createComposeRule()

    @Test
    fun theFirstAnchorSeedsTheHolderWithoutAReport() {
        // The first composition states the opening anchor; it is a seed, not a
        // transition, so the native state starts there and reports nothing.
        val ir = mutableStateOf(parse(swipe(value = "startToEnd")))
        val actions = mutableListOf<Action>()
        compose.setContent { PyComposeTheme { renderer(actions).Render(ir.value) } }
        compose.waitForIdle()

        assertTrue(actions.isEmpty())
        assertTrue(contentLeft() > 0.dp)

        assertTrue(actions.isEmpty())
        assertTrue(contentLeft() > 0.dp)
    }

    @Test
    fun theHostDrivesEveryAnchorAndReportsEachSettledChange() {
        val ir = mutableStateOf(parse(swipe(value = "settled")))
        val actions = mutableListOf<Action>()
        compose.setContent { PyComposeTheme { renderer(actions).Render(ir.value) } }
        compose.waitForIdle()
        assertTrue(actions.isEmpty())
        assertEquals(0.dp, contentLeft())

        compose.runOnIdle { ir.value = parse(swipe(value = "endToStart"), actions) }
        compose.waitForIdle()
        compose.waitUntil(5000) { actions.isNotEmpty() }
        assertEquals("""{"value":"endToStart"}""", actions[0].payload.toString())
        compose.waitForIdle()
        assertTrue(contentLeft() < 0.dp)

        compose.runOnIdle { ir.value = parse(swipe(value = "settled"), actions) }
        compose.waitForIdle()
        compose.waitUntil(5000) { actions.size == 2 }
        assertEquals("""{"value":"settled"}""", actions[1].payload.toString())
        compose.waitForIdle()
        assertEquals(0.dp, contentLeft())

        compose.runOnIdle { ir.value = parse(swipe(value = "startToEnd"), actions) }
        compose.waitForIdle()
        compose.waitUntil(5000) { actions.size == 3 }
        assertEquals("""{"value":"startToEnd"}""", actions[2].payload.toString())
        compose.waitForIdle()
        assertTrue(contentLeft() > 0.dp)
    }

    @Test
    fun aGestureReportsItsAnchorAndIsNotForcedBack() {
        // The app still desires the old anchor after the user swipes. The host
        // must keep the gesture's result until the app states a new anchor.
        val source = swipe(value = "settled")
        val ir = mutableStateOf(parse(source))
        val actions = mutableListOf<Action>()
        compose.setContent { PyComposeTheme { renderer(actions).Render(ir.value) } }
        compose.waitForIdle()

        compose.onRoot().performTouchInput { swipeLeft() }
        compose.waitForIdle()
        compose.waitUntil(5000) { actions.isNotEmpty() }
        assertEquals("""{"value":"endToStart"}""", actions[0].payload.toString())

        compose.runOnIdle { ir.value = parse(source, actions) }
        compose.waitForIdle()
        assertEquals(1, actions.size)
        assertTrue(contentLeft() < 0.dp)

        // The app's echo of the reported anchor is the new baseline, not a
        // second drive that would animate the same dismissal again.
        compose.runOnIdle { ir.value = parse(swipe(value = "endToStart"), actions) }
        compose.waitForIdle()
        assertEquals(1, actions.size)
    }

    @Test
    fun aDisabledDirectionCannotDismissThatWay() {
        val ir = mutableStateOf(parse(swipe(value = "settled", endToStart = false)))
        val actions = mutableListOf<Action>()
        compose.setContent { PyComposeTheme { renderer(actions).Render(ir.value) } }
        compose.waitForIdle()

        compose.onRoot().performTouchInput { swipeLeft() }
        compose.waitForIdle()
        assertTrue(actions.isEmpty())
        assertEquals(0.dp, contentLeft())

        compose.onRoot().performTouchInput { swipeRight() }
        compose.waitForIdle()
        compose.waitUntil(5000) { actions.isNotEmpty() }
        assertEquals("""{"value":"startToEnd"}""", actions[0].payload.toString())
    }

    /** The left edge of the content row: 0 when settled, offset when dismissed. */
    private fun contentLeft(): Dp = compose.onNodeWithText("Row").getBoundsInRoot().left

    private fun renderer(actions: MutableList<Action>): Renderer =
        Renderer(BuiltinComponents.registry(), ActionDispatcher { actions.add(it) })

    private fun parse(
        source: String,
        actions: List<Action> = emptyList(),
    ) = IrParser().parse(echoing(source, actions)).getOrThrow()

    private fun swipe(
        value: String?,
        endToStart: Boolean = true,
        report: Boolean = true,
    ): String {
        val props = mutableListOf<String>()
        if (value != null) {
            props.add("\"value\":\"$value\"")
        }
        if (report) {
            props.add("\"onValueChange\":{\"fields\":{},\"intent\":\"demo.swipe\"}")
        }
        if (!endToStart) {
            props.add("\"enableDismissFromEndToStart\":false")
        }
        val extra = props.joinToString("") { ",$it" }
        return """
            {"version":"0.1.0","schemaVersion":"1.23.0",
              "metadata":{"intents":{"demo.swipe":{"payload":{
                "value":{"required":true,"type":"string"}}}}},
             "root":{"id":"root","type":"SwipeToDismissBox","props":{
               "modifier":{"operations":[{"type":"fillMaxWidth","fraction":1.0}]}$extra
             },
               "children":[
                 {"id":"root.content","type":"Text","props":{"text":"Row"}},
                 {"id":"root.background","type":"Text","props":{"text":"Delete"},
                   "slot":"backgroundContent"}]}}
            """.trimIndent()
    }
}
