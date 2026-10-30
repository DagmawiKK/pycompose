package com.pycompose.ir

import com.pycompose.ir.generated.Effect
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import org.junit.jupiter.params.ParameterizedTest
import org.junit.jupiter.params.provider.ValueSource

class EffectsTest {
    private fun envelope(
        effects: String,
        schema: String = "1.4.0",
    ): String =
        """{"version":"0.1.0","schemaVersion":"$schema",
            "root":{"id":"root","type":"Text","props":{"text":"ok"}},
            "metadata":{"effects":$effects}}"""

    @Test
    fun `effects parse in declaration order with their payloads`() {
        val parsed =
            IrParser()
                .parse(
                    envelope(
                        """[{"kind":"toast","payload":{"message":"saved"}},
                {"kind":"finish","payload":{}},
                {"kind":"navigate","payload":{"route":"details"}}]""",
                    ),
                ).getOrThrow()
        val effects = Effects.read(parsed.snapshot.metadata, parsed.snapshot.schemaVersion)
        assertEquals(listOf("toast", "finish", "navigate"), effects.map { it.kind })
        assertEquals(Effect.Toast("saved"), Effect.of(effects[0]))
        assertEquals(Effect.Navigate("details"), Effect.of(effects[2]))
    }

    @Test
    fun `a snapshot without effects produces no requests`() {
        val parsed =
            IrParser()
                .parse(
                    """{"version":"0.1.0","schemaVersion":"1.4.0",
                "root":{"id":"root","type":"Text","props":{"text":"ok"}}}""",
                ).getOrThrow()
        assertTrue(Effects.read(parsed.snapshot.metadata, parsed.snapshot.schemaVersion).isEmpty())
    }

    @Test
    fun `effects are rejected on schemas that cannot carry them`() {
        val result =
            IrParser().parse(
                envelope("""[{"kind":"finish","payload":{}}]""", schema = "1.3.0"),
            )
        assertTrue(result.isFailure)
    }

    @ParameterizedTest
    @ValueSource(
        strings = [
            """[{"kind":"toast","payload":{"message":"ok"}}]""",
            """[{"kind":"finish","payload":{}}]""",
        ],
    )
    fun `well formed effects still parse through the full wire validator`(effects: String) {
        assertTrue(IrParser().parse(envelope(effects)).isSuccess, effects)
    }

    @ParameterizedTest
    @ValueSource(
        strings = [
            """{}""",
            """["toast"]""",
            """[{"kind":"toast"}]""",
            """[{"kind":"toast","payload":{},"extra":1}]""",
            """[{"kind":"reboot","payload":{}}]""",
            """[{"kind":"toast","payload":{"message":1}}]""",
            """[{"kind":"toast","payload":{"message":"ok","extra":"no"}}]""",
            """[{"kind":"navigate","payload":{}}]""",
            """[{"kind":"navigate","payload":{"route":null}}]""",
        ],
    )
    fun `malformed effect requests fail closed rather than degrading`(effects: String) {
        val result = IrParser().parse(envelope(effects))
        assertTrue(result.isFailure, effects)
        assertTrue(!result.exceptionOrNull()?.message.isNullOrBlank())
    }
}
