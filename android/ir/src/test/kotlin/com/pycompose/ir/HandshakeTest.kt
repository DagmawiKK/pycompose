package com.pycompose.ir

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
        assertEquals("Bridge protocol mismatch: host 1, app 2", refused.message)
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
    fun `the offer states the protocol and capabilities`() {
        assertEquals("""{"protocol":1,"capabilities":[]}""", Handshake.offer())
    }
}
