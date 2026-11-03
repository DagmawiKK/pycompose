package com.pycompose.ir

import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

/**
 * An expression is a value a dp or number prop holds, wherever it is written: the prop itself, a
 * binding's target, or a modifier's argument. A colour expression stays a colour prop's, and an
 * integer takes neither.
 */
class ExpressionPropsTest {
    private fun snapshot(root: String): String =
        """{"version":"0.1.0","schemaVersion":"1.23.0","root":$root}"""

    private fun parse(root: String) = IrParser().parse(snapshot(root))

    private val number = """{"type":"expression","node":{"stream":"list","name":"progress"}}"""

    private val colour =
        """{"type":"expression","node":{"op":"alpha","color":"#000000",
        "args":[{"stream":"list","name":"progress"}]}}"""

    private fun column(card: String) =
        """{"id":"list","type":"Column","props":{},"children":[$card]}"""

    private fun surface(props: String) = """{"id":"card","type":"Surface","props":{$props}}"""

    @Test
    fun `a number expression fills a dp prop`() {
        assertTrue(parse(column(surface(""""shadowElevation":$number"""))).isSuccess)
    }

    @Test
    fun `a number expression fills a modifier argument`() {
        val modifier =
            """"modifier":{"operations":[{"type":"offset","y":$number}]}"""
        assertTrue(parse(column(surface(modifier))).isSuccess)
    }

    @Test
    fun `a binding's target may be a number expression`() {
        val binding =
            """{"type":"binding","target":$number,
            "travel":{"kind":"none"},"phase":"composition"}"""
        assertTrue(parse(column(surface(""""shadowElevation":$binding"""))).isSuccess)
    }

    @Test
    fun `a colour expression does not fill a dp prop`() {
        assertTrue(parse(column(surface(""""shadowElevation":$colour"""))).isFailure)
    }

    @Test
    fun `an integer takes no expression`() {
        val text = """{"id":"card","type":"BasicText","props":{"text":"Hi","minLines":$number}}"""
        assertTrue(parse(column(text)).isFailure)
    }

    @Test
    fun `a stream names a holder that publishes it`() {
        val unknown = """{"type":"expression","node":{"stream":"card","name":"progress"}}"""
        assertTrue(parse(column(surface(""""shadowElevation":$unknown"""))).isFailure)
    }
}
