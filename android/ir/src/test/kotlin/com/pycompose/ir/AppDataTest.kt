package com.pycompose.ir

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import org.junit.jupiter.params.ParameterizedTest
import org.junit.jupiter.params.provider.ValueSource

class AppDataTest {
    private fun envelope(
        data: String,
        schema: String = "1.4.0",
    ): String =
        """{"version":"0.1.0","schemaVersion":"$schema",
            "root":{"id":"root","type":"Text","props":{"text":"ok"}},
            "metadata":{"data":$data}}"""

    @Test
    fun `app data is returned as the canonical text the app published`() {
        val parsed = IrParser().parse(envelope("""{"tasks":[{"id":1}],"draft":""}""")).getOrThrow()
        assertEquals(
            """{"draft":"","tasks":[{"id":1}]}""",
            AppData.read(parsed.snapshot.metadata, parsed.snapshot.schemaVersion),
        )
    }

    @Test
    fun `equal data yields equal text whatever order it arrived in`() {
        val first =
            IrParser()
                .parse(
                    """{"version":"0.1.0","schemaVersion":"1.4.0",
                "root":{"id":"root","type":"Text","props":{"text":"ok"}},
                "metadata":{"data":{"a":1,"b":{"x":1,"y":2}}}}""",
                ).getOrThrow()
        val second =
            IrParser()
                .parse(
                    """{"version":"0.1.0","schemaVersion":"1.4.0",
                "root":{"id":"root","type":"Text","props":{"text":"ok"}},
                "metadata":{"data":{"b":{"y":2,"x":1},"a":1}}}""",
                ).getOrThrow()
        assertEquals(
            AppData.read(first.snapshot.metadata, first.snapshot.schemaVersion),
            AppData.read(second.snapshot.metadata, second.snapshot.schemaVersion),
        )
    }

    @Test
    fun `an app that publishes nothing yields nothing to save`() {
        val parsed =
            IrParser()
                .parse(
                    """{"version":"0.1.0","schemaVersion":"1.4.0",
                "root":{"id":"root","type":"Text","props":{"text":"ok"}}}""",
                ).getOrThrow()
        assertEquals("", AppData.read(parsed.snapshot.metadata, parsed.snapshot.schemaVersion))
    }

    @Test
    fun `app data is rejected on schemas that cannot carry it`() {
        assertTrue(IrParser().parse(envelope("""{"a":1}""", schema = "1.3.0")).isFailure)
    }

    @ParameterizedTest
    @ValueSource(strings = ["""{}""", """{"tasks":[]}""", """{"nested":{"deep":[1,2]}}"""])
    fun `any object is publishable app data`(data: String) {
        assertTrue(IrParser().parse(envelope(data)).isSuccess, data)
    }

    @ParameterizedTest
    @ValueSource(strings = ["""["tasks"]""", """"tasks"""", "1", "null"])
    fun `non object app data fails closed rather than degrading`(data: String) {
        val result = IrParser().parse(envelope(data))
        assertTrue(result.isFailure, data)
        assertTrue(!result.exceptionOrNull()?.message.isNullOrBlank())
    }

    @Test
    fun `app data survives alongside effects and bindings`() {
        val parsed =
            IrParser()
                .parse(
                    """{"version":"0.1.0","schemaVersion":"1.4.0",
                "root":{"id":"root","type":"Button",
                    "props":{"text":"Add","onClick":{"fields":{},"intent":"main.add_task"}}},
                "metadata":{"effects":[{"kind":"finish","payload":{}}],
                    "intents":{"main.add_task":{"payload":{}}},
                    "data":{"draft":"hi"}}}""",
                ).getOrThrow()
        assertEquals(
            """{"draft":"hi"}""",
            AppData.read(parsed.snapshot.metadata, parsed.snapshot.schemaVersion),
        )
        assertEquals(1, Effects.read(parsed.snapshot.metadata, parsed.snapshot.schemaVersion).size)
    }
}
