package com.pycompose.program

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import org.junit.jupiter.params.ParameterizedTest
import org.junit.jupiter.params.provider.ValueSource

private const val DOT = """{"draw":"dot","args":[{"integer":1},{"arg":0}]}"""

class DrawingsTest {
    private val functions =
        FunctionContract(
            depth = 4,
            nodes = 16,
            arguments = 3,
            signatures = mapOf("lt" to mapOf(listOf("integer", "integer") to "boolean")),
        )
    private val contract =
        DrawContract(
            nodes = 32,
            draws = 8,
            repeat = 4,
            loops = 2,
            calls = mapOf("dot" to listOf("integer", "number")),
        )

    private fun program(body: String): JsonObject =
        Json
            .parseToJsonElement(
                """{"type":"program","params":["number","number"],"result":"draw","body":$body}""",
            ).jsonObject

    @Test
    fun `a loop runs its body once per index, which the body reads`() {
        val drawing =
            Drawings.read(
                program(
                    """[{"repeat":3,"body":[{"if":{"op":"lt","args":[{"loop":0},{"integer":2}]},
                    "then":[{"draw":"dot","args":[{"loop":0},{"arg":0}]}],"else":[]}]}]""",
                ),
                functions,
                contract,
            )
        val drawn = mutableListOf<List<Any>>()
        drawing.draw(5.0, 6.0) { drawn += it.args }
        assertEquals(listOf(listOf(0L, 5.0), listOf(1L, 5.0)), drawn)
    }

    @Test
    fun `a bound drawing reads its bound arguments after the canvas's size`() {
        val program = """{"type":"program","params":["number","number","integer"],"result":"draw",
            "body":[{"draw":"dot","args":[{"arg":2},{"arg":1}]}]}"""
        val bound =
            BoundDrawing.read(
                json("""{"type":"bound","program":$program,"args":[7]}"""),
                functions,
                contract,
            )
        val drawn = mutableListOf<List<Any>>()
        bound.draw(5.0, 6.0) { drawn += it.args }
        assertEquals(listOf(listOf(7L, 6.0)), drawn)
        listOf("[]", "[7.5]", "[true]", "[7, 8]", "[\"7\"]").forEach { args ->
            assertThrows<RuntimeException> {
                BoundDrawing.read(
                    json("""{"type":"bound","program":$program,"args":$args}"""),
                    functions,
                    contract,
                )
            }
        }
        assertThrows<RuntimeException> { BoundDrawing.read(json(program), functions, contract) }
    }

    private fun json(text: String): JsonObject = Json.parseToJsonElement(text).jsonObject

    @ParameterizedTest
    @ValueSource(
        strings = [
            """[{"draw":"spiral","args":[]}]""",
            """[{"draw":"dot","args":[{"number":1.0},{"number":1.0}]}]""",
            """[{"repeat":2.5,"body":[]}]""",
            """[{"repeat":5,"body":[]}]""",
            """[{"repeat":4,"body":[{"repeat":4,"body":[$DOT]}]}]""",
            """[{"repeat":2,"body":[{"draw":"dot","args":[{"loop":1},{"arg":0}]}]}]""",
            """[{"if":{"integer":1},"then":[],"else":[]}]""",
        ],
    )
    fun `a malformed, mistyped or too costly drawing is refused`(body: String) {
        assertThrows<RuntimeException> { Drawings.read(program(body), functions, contract) }
    }
}
