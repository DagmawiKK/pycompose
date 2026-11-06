package com.pycompose.host.ui.holders

import androidx.compose.runtime.mutableStateOf
import com.pycompose.host.ui.BuiltinComponents
import com.pycompose.host.ui.PyComposeTheme
import com.pycompose.ir.IrParser
import com.pycompose.ir.ValidatedIr
import com.pycompose.renderer.Action
import com.pycompose.renderer.ActionDispatcher
import com.pycompose.renderer.Renderer
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** A range slider, derived as the slider is: both ends driven, reported where they settle. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class RangeSliderStateTest {
    @get:Rule val compose =
        androidx.compose.ui.test.junit4
            .createComposeRule()

    @Test
    fun theAppMovesBothEndsAndHearsWhereTheyLandedOnTheirTicks() {
        // Four steps between 0 and 1 put ticks at fifths: 0.33 lands on 0.4 and 0.9 on 0.8.
        val ir = mutableStateOf(parse(range(start = "0.0", end = "1.0")))
        val actions = mutableListOf<Action>()
        compose.setContent {
            PyComposeTheme {
                Renderer(BuiltinComponents.registry(), ActionDispatcher { actions.add(it) })
                    .Render(ir.value)
            }
        }
        compose.waitForIdle()
        compose.runOnIdle { actions.clear() }

        compose.runOnIdle { ir.value = parse(range(start = "0.33", end = "0.9")) }
        compose.waitForIdle()

        val last = actions.last().payload
        assertEquals(JsonPrimitive(0.4f), last["activeRangeStart"])
        assertEquals(JsonPrimitive(0.8f), last["activeRangeEnd"])
    }

    private fun parse(source: String): ValidatedIr = IrParser().parse(source).getOrThrow()

    private fun range(
        start: String,
        end: String,
    ): String =
        """
        {"version":"0.1.0","schemaVersion":"1.23.0","metadata":{"intents":{
          "demo.range":{"payload":{
            "activeRangeStart":{"required":true,"type":"number"},
            "activeRangeEnd":{"required":true,"type":"number"}}}}},
         "root":{"id":"root","type":"RangeSlider","props":{
           "valueRange":{"type":"Range","start":0.0,"end":1.0},"steps":4,
           "activeRangeStart":$start,"activeRangeEnd":$end,
           "onValueChangeFinished":{"fields":{},"intent":"demo.range"}}}}
        """.trimIndent()
}
