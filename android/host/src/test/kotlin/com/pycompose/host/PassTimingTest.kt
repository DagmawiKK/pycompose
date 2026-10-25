package com.pycompose.host

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Test

class PassTimingTest {
    @Test
    fun oneLineCarriesEveryStagePythonsSplitAndTheTotal() {
        val timing =
            PassTiming(
                queue = 1.0,
                python = 40.0,
                pull = 2.0,
                apply = 3.0,
                phases = """{"view":30.5,"serialize":4.0}""",
                commands = 2,
                appliedAt = 1_000_000L,
            )
        // The frame's share is measured from the apply to the frame drawn: 8 ms here.
        val line = Json.parseToJsonElement(timing.line(drawnAt = 9_000_000L)).jsonObject

        assertEquals(8.0, line.getValue("frame").jsonPrimitive.double, 0.0)
        assertEquals(54.0, line.getValue("total").jsonPrimitive.double, 0.0)
        assertEquals(30.5, line.getValue("view").jsonPrimitive.double, 0.0)
        assertEquals(2, line.getValue("commands").jsonPrimitive.int)
    }

    @Test
    fun anUnreadablePythonSplitStillLogsTheHostStages() {
        val timing = PassTiming(1.0, 2.0, 3.0, 4.0, "not json", 1, 0L)
        val line = Json.parseToJsonElement(timing.line(drawnAt = 0L)).jsonObject

        assertEquals(10.0, line.getValue("total").jsonPrimitive.double, 0.0)
    }
}
