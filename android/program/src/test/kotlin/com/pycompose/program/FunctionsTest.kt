package com.pycompose.program

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows

class FunctionsTest {
    private val contract =
        FunctionContract(
            depth = 4,
            nodes = 16,
            arguments = 2,
            signatures =
                mapOf(
                    "floorDiv" to mapOf(listOf("integer", "integer") to "integer"),
                    "mod" to mapOf(listOf("integer", "integer") to "integer"),
                    "lt" to mapOf(listOf("integer", "integer") to "boolean"),
                    "neg" to mapOf(listOf("integer") to "integer"),
                    "ne" to mapOf(listOf("string", "string") to "boolean"),
                ),
        )

    private fun program(
        params: String,
        result: String,
        body: String,
    ): JsonObject =
        Json
            .parseToJsonElement(
                """{"type":"program","params":$params,"result":"$result","body":$body}""",
            ).jsonObject

    @Test
    fun `an enum argument is its spelling, compared by equality`() {
        // A drawer asks whether it may settle at an anchor; this one may not close.
        val keep =
            Functions.read(
                program(
                    """["string"]""",
                    "boolean",
                    """{"op":"ne","args":[{"arg":0},{"string":"closed"}]}""",
                ),
                contract,
            )

        assertEquals(true, keep.call("open"))
        assertEquals(false, keep.call("closed"))
    }

    @Test
    fun `a function prop's program takes the host's arguments, then its bound ones`() {
        val bound =
            Json
                .parseToJsonElement(
                    """{"type":"bound","args":["open"],"program":""" +
                        program(
                            """["string","string"]""",
                            "boolean",
                            """{"op":"ne","args":[{"arg":0},{"arg":1}]}""",
                        ) + "}",
                ).jsonObject
        val call = BoundFunction.read(bound, listOf("string"), "boolean", contract)

        assertEquals(false, call.call("open"))
        assertEquals(true, call.call("closed"))
        assertThrows<IllegalArgumentException> {
            BoundFunction.read(bound, listOf("integer"), "boolean", contract)
        }
    }

    @Test
    fun `a zero divisor gives zero rather than throwing in the frame`() {
        val divide =
            Functions.read(
                program(
                    """["integer","integer"]""",
                    "integer",
                    """{"op":"floorDiv","args":[{"arg":0},{"arg":1}]}""",
                ),
                contract,
            )
        assertEquals(-4L, divide.call(-7L, 2L))
        assertEquals(0L, divide.call(7L, 0L))
    }

    @Test
    fun `a program the catalog's table does not type is refused`() {
        assertThrows<IllegalStateException> {
            Functions.read(
                program(
                    """["integer"]""",
                    "boolean",
                    """{"op":"lt","args":[{"arg":0},{"number":1.0}]}""",
                ),
                contract,
            )
        }
        assertThrows<IllegalArgumentException> {
            Functions.read(
                program("[]", "integer", """{"op":"times","args":[{"integer":1},{"integer":2}]}"""),
                contract,
            )
        }
        assertThrows<IllegalArgumentException> {
            Functions.read(program("[]", "boolean", """{"integer":1}"""), contract)
        }
        assertThrows<IllegalStateException> {
            Functions.read(program("[]", "integer", """{"integer":1.0}"""), contract)
        }
    }

    @Test
    fun `a program past the catalog's limits is refused`() {
        val deep = (1..4).fold("""{"arg":0}""") { body, _ -> """{"op":"neg","args":[$body]}""" }
        assertThrows<IllegalArgumentException> {
            Functions.read(program("""["integer"]""", "integer", deep), contract)
        }
        assertThrows<IllegalArgumentException> {
            Functions.read(
                program("""["integer","integer","integer"]""", "integer", """{"arg":0}"""),
                contract,
            )
        }
    }
}
