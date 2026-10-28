package com.pycompose.ir

import com.pycompose.ir.generated.IrContract
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows

class HandshakeTest {
    @Test
    fun `a matching app is accepted`() {
        Handshake.accept("""{"capabilities":[],"protocol":${Handshake.PROTOCOL}}""")
    }

    @Test
    fun `a different protocol is refused naming both`() {
        val refused =
            assertThrows<IllegalStateException> {
                Handshake.accept("""{"capabilities":[],"protocol":${Handshake.PROTOCOL + 1}}""")
            }
        assertEquals(
            "Bridge protocol mismatch: host ${Handshake.PROTOCOL}, app ${Handshake.PROTOCOL + 1}",
            refused.message,
        )
    }

    @Test
    fun `an app lacking a required capability is refused naming it`() {
        val refused =
            assertThrows<IllegalStateException> {
                Handshake.accept(
                    """{"capabilities":["surfaces"],"protocol":${Handshake.PROTOCOL}}""",
                    required = setOf("surfaces", "windows"),
                )
            }
        assertEquals("App lacks capabilities: windows", refused.message)
    }

    @Test
    fun `the offer states the protocol, capabilities and the components rendered`() {
        val offer = Json.parseToJsonElement(Handshake.offer()).jsonObject
        assertEquals(Handshake.PROTOCOL, offer.getValue("protocol").jsonPrimitive.int)
        assertEquals(JsonArray(emptyList()), offer.getValue("capabilities"))
        val components = offer.getValue("components").jsonArray.map { it.jsonPrimitive.content }
        assertEquals(IrContract.components.keys.sorted(), components)
    }
}
