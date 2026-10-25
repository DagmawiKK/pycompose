package com.pycompose.ir

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class AppBindingsTest {
    private fun bindings(rule: String): Map<String, AppBinding> =
        AppBindings.read(
            Json
                .parseToJsonElement(
                    """{"actionBindings":{"app.pick.date":{"handlerId":"pick.date",
                    "payload":{"selectedDateMillis":$rule},"bound":{}}}}""",
                ).jsonObject,
            "1.23.0",
        )

    private fun report(value: kotlinx.serialization.json.JsonElement) =
        JsonObject(mapOf("selectedDateMillis" to value))

    @Test
    fun `a nullable payload field accepts the null a cleared holder reports`() {
        val nullable = bindings("""{"type":"integer","required":true,"nullable":true}""")
        assertTrue(
            AppBindings.validatePayload("app.pick.date", report(JsonNull), nullable).isSuccess,
        )
        assertTrue(
            AppBindings
                .validatePayload(
                    "app.pick.date",
                    report(JsonPrimitive(7)),
                    nullable,
                ).isSuccess,
        )

        val strict = bindings("""{"type":"integer","required":true}""")
        assertTrue(AppBindings.validatePayload("app.pick.date", report(JsonNull), strict).isFailure)
    }
}
