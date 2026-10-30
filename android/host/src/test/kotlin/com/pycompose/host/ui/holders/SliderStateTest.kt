package com.pycompose.host.ui.holders

import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.semantics.ProgressBarRangeInfo
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assert
import androidx.compose.ui.test.junit4.StateRestorationTester
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.performTouchInput
import androidx.compose.ui.test.swipeRight
import com.pycompose.host.intent
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

/** The slider half of the state-projection protocol, end to end. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class SliderStateTest {
    @get:Rule val compose = createComposeRule()

    @Test
    fun theAppValueDrivesTheHolderAndReportsItsSettledChange() {
        val ir = mutableStateOf(parse(slider(value = "0.75")))
        val actions = mutableListOf<Action>()
        compose.setContent { PyComposeTheme { renderer(actions).Render(ir.value) } }

        compose.waitForIdle()

        compose
            .onNode(SemanticsMatcher.keyIsDefined(SemanticsProperties.ProgressBarRangeInfo))
            .assert(
                SemanticsMatcher.expectValue(
                    SemanticsProperties.ProgressBarRangeInfo,
                    ProgressBarRangeInfo(0.75f, 0f..1f, steps = 0),
                ),
            )
        assertEquals(JsonPrimitive(0.75f), actions.single().payload["value"])
    }

    @Test
    fun aChangedAppValueDrivesTheExistingHolderAndReportsOnce() {
        val ir = mutableStateOf(parse(slider(value = "0.25")))
        val actions = mutableListOf<Action>()
        compose.setContent { PyComposeTheme { renderer(actions).Render(ir.value) } }
        compose.waitForIdle()

        compose.runOnIdle { ir.value = parse(slider(value = "0.75")) }
        compose.waitForIdle()

        compose
            .onNode(SemanticsMatcher.keyIsDefined(SemanticsProperties.ProgressBarRangeInfo))
            .assert(
                SemanticsMatcher.expectValue(
                    SemanticsProperties.ProgressBarRangeInfo,
                    ProgressBarRangeInfo(0.75f, 0f..1f, steps = 0),
                ),
            )
        assertEquals(
            listOf(JsonPrimitive(0.25f), JsonPrimitive(0.75f)),
            actions.map { it.payload["value"] },
        )
        compose.runOnIdle { ir.value = parse(slider(value = "0.75")) }
        compose.waitForIdle()
        assertEquals(2, actions.size)
    }

    @Test
    fun aRangeWithoutAValueStartsTheHolderAtItsFloor() {
        // Nothing stated: the holder sits at the range's floor and the gesture
        // is the user's alone.
        val ir = mutableStateOf(parse(slider(value = null)))
        val actions = mutableListOf<Action>()
        compose.setContent { PyComposeTheme { renderer(actions).Render(ir.value) } }

        compose.waitForIdle()

        compose
            .onNode(SemanticsMatcher.keyIsDefined(SemanticsProperties.ProgressBarRangeInfo))
            .assert(
                SemanticsMatcher.expectValue(
                    SemanticsProperties.ProgressBarRangeInfo,
                    ProgressBarRangeInfo(0f, 0f..1f, steps = 0),
                ),
            )
        assertTrue(actions.isEmpty())
    }

    @Test
    fun aGestureTheAppDidNotCauseSettlesAndReportsTheValue() {
        // The drag is the user's; the settled value crosses the wire under the
        // one field its type fits, and the app learns where the thumb landed.
        val ir = mutableStateOf(parse(slider(value = "0.25")))
        val actions = mutableListOf<Action>()
        compose.setContent { PyComposeTheme { renderer(actions).Render(ir.value) } }
        compose.waitForIdle()
        compose.runOnIdle { actions.clear() }

        compose
            .onNode(SemanticsMatcher.keyIsDefined(SemanticsProperties.ProgressBarRangeInfo))
            .performTouchInput { swipeRight() }

        compose.waitUntil(5000) { actions.isNotEmpty() }
        assertEquals(intent("demo.slider"), actions[0].actionId)
        val settled = actions[0].payload["value"]
        assertTrue(settled is JsonPrimitive && !settled.isString)
    }

    @Test
    fun aNewReportBindingTakesEffectWithoutReplacingTheHolder() {
        val ir = mutableStateOf(parse(slider(value = "0.25")))
        val actions = mutableListOf<Action>()
        compose.setContent { PyComposeTheme { renderer(actions).Render(ir.value) } }
        compose.waitForIdle()
        compose.runOnIdle { actions.clear() }

        compose.runOnIdle {
            ir.value = parse(slider(value = "0.25", report = "demo.settled"))
        }
        compose.waitForIdle()
        compose
            .onNode(SemanticsMatcher.keyIsDefined(SemanticsProperties.ProgressBarRangeInfo))
            .performTouchInput { swipeRight() }
        compose.waitForIdle()

        assertEquals(intent("demo.settled"), actions.single().actionId)
    }

    @Test
    fun anInitialSteppedValueIsNormalizedToItsNativeTick() {
        val ir = parse(slider(value = "0.3", steps = 1))
        val actions = mutableListOf<Action>()
        compose.setContent { PyComposeTheme { renderer(actions).Render(ir) } }
        compose.waitForIdle()

        compose
            .onNode(SemanticsMatcher.keyIsDefined(SemanticsProperties.ProgressBarRangeInfo))
            .assert(
                SemanticsMatcher.expectValue(
                    SemanticsProperties.ProgressBarRangeInfo,
                    ProgressBarRangeInfo(0.5f, 0f..1f, steps = 1),
                ),
            )
        assertEquals(JsonPrimitive(0.5f), actions.single().payload["value"])
    }

    @Test
    fun restoringTheHolderDoesNotReapplyAnUnchangedDesiredValue() {
        val restoration = StateRestorationTester(compose)
        val ir = parse(slider(value = "0.25"))
        val actions = mutableListOf<Action>()
        restoration.setContent { PyComposeTheme { renderer(actions).Render(ir) } }
        compose.waitForIdle()
        val slider =
            compose.onNode(
                SemanticsMatcher.keyIsDefined(SemanticsProperties.ProgressBarRangeInfo),
            )
        slider.performTouchInput { swipeRight() }
        compose.waitForIdle()
        val selected = slider.fetchSemanticsNode().config[SemanticsProperties.ProgressBarRangeInfo]
        assertTrue(selected.current > 0.25f)
        compose.runOnIdle { actions.clear() }

        restoration.emulateSavedInstanceStateRestore()
        compose.waitForIdle()

        assertEquals(
            selected,
            slider.fetchSemanticsNode().config[SemanticsProperties.ProgressBarRangeInfo],
        )
        assertTrue(actions.isEmpty())
    }

    private fun renderer(actions: MutableList<Action>): Renderer =
        Renderer(BuiltinComponents.registry(), ActionDispatcher { actions.add(it) })

    private fun parse(source: String): ValidatedIr = IrParser().parse(source).getOrThrow()

    private fun slider(
        value: String?,
        report: String = "demo.slider",
        steps: Int = 0,
    ): String {
        val stated = if (value != null) ",\"value\":$value" else ""
        return """
            {"version":"0.1.0","schemaVersion":"1.23.0","metadata":{"intents":{
              "$report":{"payload":{"value":{"required":true,"type":"number"}}}}},
             "root":{"id":"root","type":"Slider","props":{
               "valueRange":{"type":"Range","start":0.0,"end":1.0},
               "steps":$steps,
                "onValueChangeFinished":{"fields":{},"intent":"$report"}$stated}}}
            """.trimIndent()
    }
}
