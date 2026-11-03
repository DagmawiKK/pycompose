package com.pycompose.renderer

import androidx.compose.ui.unit.dp
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Test

/**
 * A dp or number value may stand as an expression over a holder's streams, so the host reads
 * both forms through one decode, and a holder that is not composed yet reads as at rest.
 */
class ExpressionNumberTest {
    private val streams: Streams = mapOf("list" to mapOf("progress" to { 0.25f }))

    private fun expression(source: String) = Json.parseToJsonElement(source)

    private val reading =
        expression(
            """{"type":"expression","node":{"op":"times",
            "args":[{"stream":"list","name":"progress"},{"number":8}]}}""",
        )

    @Test
    fun `a plain number reads as itself`() {
        assertEquals(4.0, numberValue(JsonPrimitive(4), emptyMap()), 0.0)
        assertEquals(2.5, numberValue(JsonPrimitive(2.5), emptyMap()), 0.0)
    }

    @Test
    fun `an expression reads the stream it names`() {
        assertEquals(2.0, numberValue(reading, streams), 1e-6)
    }

    @Test
    fun `an expression whose holder is not composed reads as at rest`() {
        assertEquals(0.0, numberValue(reading, emptyMap()), 0.0)
    }

    @Test
    fun `a dp reads the same number in density-independent pixels`() {
        assertEquals(4.dp, dpValue(JsonPrimitive(4), emptyMap()))
        assertEquals(2.dp, dpValue(reading, streams))
    }

    @Test
    fun `an expression object is recognised, a plain number is not`() {
        assertEquals("expression", (reading.jsonObject["type"] as JsonPrimitive).content)
        assertEquals(4.0, numberValue(JsonPrimitive(4), streams), 0.0)
    }
}
