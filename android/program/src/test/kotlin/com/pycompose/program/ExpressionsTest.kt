package com.pycompose.program

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows

class ExpressionsTest {
    private val contract =
        Contract(
            depth = 8,
            nodes = 32,
            operations = setOf("times", "plus", "minus", "clamp", "alpha", "mix"),
            streamNames = setOf("progress"),
        )

    private fun parse(source: String): JsonObject = Json.parseToJsonElement(source).jsonObject

    private val scrim =
        parse(
            """{"type":"expression","node":{"op":"alpha","color":"#000000",
            "args":[{"op":"times","args":[{"stream":"nav","name":"progress"},{"number":0.6}]}]}}""",
        )

    @Test
    fun `a checked expression names the streams it reads`() {
        assertEquals(listOf("nav" to "progress"), Expressions.validate(scrim, "color", contract))
    }

    @Test
    fun `an expression past the catalog's limits is refused`() {
        assertThrows<IllegalArgumentException> {
            Expressions.validate(scrim, "color", contract.copy(depth = 2))
        }
    }

    @Test
    fun `numbers evaluate from streams, and a colour stops at its colours and fraction`() {
        val node = scrim.getValue("node") as JsonObject
        val term =
            colour(node) { holder, name ->
                if (holder == "nav" &&
                    name == "progress"
                ) {
                    0.5f
                } else {
                    null
                }
            }
        assertEquals(ColourTerm.Alpha(0xFF000000.toInt(), 0.3f), term)
        assertEquals(ColourTerm.Alpha(0xFF000000.toInt(), 0f), colour(node) { _, _ -> null })
    }
}
