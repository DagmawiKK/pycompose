package com.pycompose.renderer

import com.pycompose.ir.AppBinding
import com.pycompose.ir.PropertyRule
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Resolving which declared field an inbound event value belongs to.
 *
 * The vocabulary is the point: an app's `int` field travels as "integer", not
 * "number", so a matcher keyed on a single type name silently misses exactly the
 * case it exists to handle. These assert on the *field chosen*, not merely that
 * something was dispatched -- dispatching the right value to the wrong field is
 * the bug being guarded against.
 */
class EventResolutionTest {
    private val reported = mutableListOf<String>()
    private val dispatched = mutableListOf<Pair<String, String>>()

    /** Resolve one event, returning the field it was dispatched to, or null. */
    private fun event(
        fields: Map<String, String>,
        value: JsonPrimitive,
    ): String? {
        reported.clear()
        dispatched.clear()
        val binding =
            AppBinding(
                fields.mapValues { PropertyRule(type = it.value) },
                JsonObject(emptyMap()),
            )
        val context =
            RenderContext(
                ActionDispatcher { action ->
                    dispatched.add(
                        action.payload.keys.single() to
                            action.payload.values
                                .single()
                                .toString(),
                    )
                },
                Renderer(
                    ComponentRegistry.Builder().build(),
                    ActionDispatcher {},
                    debug = true,
                    report = { reported.add(it) },
                ),
                bindings = mapOf(BINDING to binding),
            )
        context.event(BINDING, value)
        return dispatched.singleOrNull()?.first
    }

    private fun value(
        fields: Map<String, String>,
        primitive: JsonPrimitive,
    ): String? {
        event(fields, primitive)
        return dispatched.singleOrNull()?.second
    }

    @Test
    fun `an integer field is chosen for a numeric value`() {
        assertEquals(
            "count",
            event(mapOf("count" to "integer", "flag" to "boolean"), JsonPrimitive(7)),
        )
    }

    @Test
    fun `a number field is chosen for a fractional value`() {
        assertEquals(
            "ratio",
            event(mapOf("ratio" to "number", "flag" to "boolean"), JsonPrimitive(1.5)),
        )
    }

    @Test
    fun `a boolean field is still chosen for a boolean`() {
        assertEquals(
            "done",
            event(mapOf("done" to "boolean", "count" to "integer"), JsonPrimitive(true)),
        )
    }

    @Test
    fun `a string field is still chosen for a string`() {
        assertEquals(
            "title",
            event(mapOf("title" to "string", "count" to "integer"), JsonPrimitive("hi")),
        )
    }

    @Test
    fun `the chosen field carries the value unchanged`() {
        assertEquals("7", value(mapOf("count" to "integer", "flag" to "boolean"), JsonPrimitive(7)))
        assertEquals(
            "true",
            value(mapOf("done" to "boolean", "count" to "integer"), JsonPrimitive(true)),
        )
        assertEquals(
            "\"hi\"",
            value(mapOf("title" to "string", "count" to "integer"), JsonPrimitive("hi")),
        )
    }

    @Test
    fun `a bound field is not offered as an event target`() {
        // noteId is supplied by the binding, so only "count" can receive an event.
        val binding =
            AppBinding(
                mapOf(
                    "noteId" to PropertyRule(type = "integer"),
                    "count" to PropertyRule(type = "integer"),
                ),
                JsonObject(mapOf("noteId" to JsonPrimitive(3))),
            )
        reported.clear()
        dispatched.clear()
        val context =
            RenderContext(
                ActionDispatcher { dispatched.add(it.payload.keys.single() to "") },
                Renderer(
                    ComponentRegistry.Builder().build(),
                    ActionDispatcher {},
                    true,
                ) { reported.add(it) },
                bindings = mapOf(BINDING to binding),
            )
        context.event(BINDING, JsonPrimitive(9))
        assertEquals(listOf("count"), dispatched.map { it.first })
    }

    @Test
    fun `two numeric fields are ambiguous and are reported rather than guessed`() {
        assertNull(event(mapOf("count" to "integer", "total" to "integer"), JsonPrimitive(3)))
        assertTrue(reported.single(), reported.isNotEmpty())
        assertTrue(reported.single(), reported.single().contains("count"))
    }

    @Test
    fun `a numeric value with no numeric field is reported`() {
        assertNull(event(mapOf("title" to "string", "flag" to "boolean"), JsonPrimitive(3)))
        assertTrue(reported.single(), reported.isNotEmpty())
    }

    private companion object {
        const val BINDING = "app.main.actions.handler.instance"
    }
}
