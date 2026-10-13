package com.pycompose.renderer

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class ResolutionTest {
    @Test
    fun `props return failures rather than throwing`() {
        assertEquals(Color(0xff123456), PropResolver.color("#123456").getOrThrow())
        assertEquals(Color(0x80123456), PropResolver.color("#80123456").getOrThrow())
        assertTrue(PropResolver.color("bad").isFailure)
        assertTrue(PropResolver.dp(Double.NaN).isFailure)
        assertTrue(PropResolver.dp(-1.0).isFailure)
        assertEquals(8.dp, PropResolver.dp(8.0).getOrThrow())
        assertTrue(PropResolver.horizontal("bad").isFailure)
        assertTrue(PropResolver.durationMs(-1).isFailure)
    }

    @Test
    fun `dispatcher transports arbitrary ids and data without interpreting them`() {
        val actions = mutableListOf<Action>()
        val dispatcher = ActionDispatcher { actions.add(it) }
        val payload = buildJsonObject { put("value", "Ada") }
        dispatcher.dispatch("app.profile.change", payload)
        assertEquals(Action("app.profile.change", payload), actions.single())
        assertEquals(
            "app.profile.change",
            Json
                .parseToJsonElement(
                    actions.single().toJson(),
                ).jsonObject["actionId"]
                ?.jsonPrimitive
                ?.content,
        )
    }

    @Test
    fun `modifier program fails as a whole on malformed operations`() {
        val builder = ModifierBuilder(ActionDispatcher {})
        val malformed =
            Json
                .parseToJsonElement(
                    """{"operations":[
                {"type":"padding","value":8},{"type":"unknown"}
            ]}""",
                ).jsonObject
        assertTrue(builder.build(malformed).isFailure)
        val valid =
            Json
                .parseToJsonElement(
                    """{"operations":[
                {"type":"padding","value":8},{"type":"padding","value":4},
                {"type":"clip","shape":"circle"}
            ]}""",
                ).jsonObject
        assertEquals(3, builder.build(valid).getOrThrow().foldIn(0) { count, _ -> count + 1 })
    }
}
