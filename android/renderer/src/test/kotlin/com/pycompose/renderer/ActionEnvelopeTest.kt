package com.pycompose.renderer

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

/** The envelope a tap sends Python carries the host's trace id, and nothing when untraced. */
class ActionEnvelopeTest {
    @Test
    fun `a traced action names its trace and an untraced one names none`() {
        val traced = Json.parseToJsonElement(Action("increment", trace = "t7").toJson()).jsonObject
        assertEquals(JsonPrimitive("t7"), traced["trace"])

        val untraced = Json.parseToJsonElement(Action("increment").toJson()).jsonObject
        assertFalse("trace" in untraced)
        assertEquals(JsonObject(emptyMap()), untraced["payload"])
    }
}
