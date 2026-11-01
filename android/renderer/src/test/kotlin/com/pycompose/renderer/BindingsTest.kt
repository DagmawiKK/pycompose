package com.pycompose.renderer

import androidx.compose.animation.core.VectorConverter
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshots.Snapshot
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.unit.Dp
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.double
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34], application = android.app.Application::class)
class BindingsTest {
    @get:Rule val compose = createComposeRule()

    private fun bound(to: Double): JsonElement =
        Json.parseToJsonElement(
            """{"type":"binding","target":$to,""" +
                """"travel":{"kind":"tween","durationMs":400,"delayMs":0},""" +
                """"phase":"composition"}""",
        )

    @Test
    fun `a bound value travels to each new target on the host's clock`() {
        var wire by mutableStateOf(bound(0.0))
        var seen = -1f
        compose.mainClock.autoAdvance = false
        compose.setContent {
            seen =
                bindingState(wire, Float.VectorConverter) {
                    it.jsonPrimitive.double.toFloat()
                }.value
        }
        compose.mainClock.advanceTimeByFrame()
        assertEquals(0f, seen)

        // One snapshot states a new target; no further input drives the frames.
        wire = bound(1.0)
        Snapshot.sendApplyNotifications()
        val trace = mutableListOf<Float>()
        repeat(12) {
            compose.mainClock.advanceTimeByFrame()
            trace += seen
        }
        assertTrue("midway, not jumped: $trace", trace.any { it > 0f && it < 1f })
        compose.mainClock.advanceTimeBy(400)
        assertEquals(1f, seen)
    }

    @Test
    fun `a plain value is read as it stands`() {
        var seen = -1f
        compose.setContent {
            seen =
                bindingState(JsonPrimitive(0.25), Float.VectorConverter) {
                    it.jsonPrimitive.double.toFloat()
                }.value
        }
        compose.waitForIdle()
        assertEquals(0.25f, seen)
    }

    @Test
    fun `the converter decides the type, not the call site`() {
        var seen: Dp? = null
        compose.setContent {
            seen =
                bindingState(
                    bound(8.0),
                    Dp.VectorConverter,
                ) { Dp(it.jsonPrimitive.double.toFloat()) }
                    .value
        }
        compose.waitForIdle()
        assertEquals(Dp(8f), seen)
    }
}
