package com.pycompose.program

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows

class BindingsTest {
    private fun parse(source: String): JsonObject = Json.parseToJsonElement(source).jsonObject

    private fun binding(phase: String): JsonObject =
        parse(
            """{"type":"binding","target":0.5,""" +
                """"travel":{"kind":"none"},"phase":"$phase"}""",
        )

    @Test
    fun `a binding reads its target, travel and phase`() {
        val read = Bindings.read(binding("draw"))
        assertEquals(Travel.None, read.travel)
        assertEquals(Phase.Draw, read.phase)
    }

    @Test
    fun `a call site reads a binding only in the phase it names`() {
        val read = Bindings.read(binding("composition"))
        assertEquals(Phase.Composition, read.at(Phase.Composition).phase)
    }

    @Test
    fun `a binding naming another phase is refused`() {
        val read = Bindings.read(binding("layout"))
        val failure = assertThrows<IllegalArgumentException> { read.at(Phase.Composition) }
        assertEquals(
            "this prop is read in composition; a layout binding cannot stand here",
            failure.message,
        )
    }

    @Test
    fun `a phase outside the closed three is refused`() {
        assertThrows<IllegalStateException> { Bindings.read(binding("pointer")) }
    }

    @Test
    fun `a travel outside the closed three is refused`() {
        assertThrows<IllegalStateException> {
            Bindings.read(
                parse(
                    """{"type":"binding","target":0.5,""" +
                        """"travel":{"kind":"bounce"},"phase":"draw"}""",
                ),
            )
        }
    }
}
