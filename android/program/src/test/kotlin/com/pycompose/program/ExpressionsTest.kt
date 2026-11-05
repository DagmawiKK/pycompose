package com.pycompose.program

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNull
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

    @Test
    fun `a prop type takes the expression kind it holds`() {
        assertEquals("color", Expressions.kindOf("color"))
        assertEquals("number", Expressions.kindOf("dp"))
        assertEquals("number", Expressions.kindOf("number"))
        assertNull(Expressions.kindOf("integer"))
        assertNull(Expressions.kindOf("string"))
    }

    @Test
    fun `a numeric expression is checked as a number`() {
        val numeric =
            parse(
                """{"type":"expression","node":{"op":"times",
                "args":[{"stream":"list","name":"progress"},{"number":4}]}}""",
            )
        assertEquals(
            listOf("list" to "progress"),
            Expressions.validate(numeric, "number", contract),
        )
        assertThrows<IllegalArgumentException> {
            Expressions.validate(numeric, "color", contract)
        }
    }

    @Test
    fun `targets reads a prop, a binding's target and a modifier argument`() {
        val root =
            parse(
                """{"id":"list","type":"Column","props":{
                "modifier":{"operations":[{"type":"offset",
                "y":{"type":"expression","node":{"stream":"list","name":"progress"}}}]}},
                "children":[
                  {"id":"card","type":"Surface","props":{
                    "shadowElevation":{"type":"binding",
                    "target":{"type":"expression","node":{"stream":"list","name":"progress"}},
                    "travel":{"kind":"none"},"phase":"layout"}}}]}""",
            )
        val reads = mutableListOf<String>()
        Expressions.targets(
            root,
            contract,
            { type, prop ->
                Expressions.kindOf(
                    if (type == "Surface" &&
                        prop == "shadowElevation"
                    ) {
                        "dp"
                    } else {
                        null
                    },
                )
            },
            { modifier, argument ->
                Expressions.kindOf(
                    if (modifier == "offset" &&
                        argument == "y"
                    ) {
                        "dp"
                    } else {
                        null
                    },
                )
            },
        ) { node ->
            val type = (node.getValue("type") as JsonPrimitive).content
            reads += type
            if (type == "Column") setOf("progress") else emptySet()
        }
        assertEquals(listOf("Column", "Column"), reads)
    }

    @Test
    fun `targets refuses a stream its holder does not publish`() {
        val root =
            parse(
                """{"id":"card","type":"Surface","props":{
                "shadowElevation":{"type":"expression",
                "node":{"stream":"card","name":"progress"}}}}""",
            )
        assertThrows<IllegalArgumentException> {
            Expressions.targets(
                root,
                contract,
                { _, _ -> "number" },
                { _, _ -> null },
            ) { emptySet() }
        }
    }
}
