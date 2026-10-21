package com.pycompose.renderer

import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.TooltipAnchorPosition
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.unit.dp
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34], application = android.app.Application::class)
class ResolutionTest {
    @get:Rule val compose = createComposeRule()

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
    @OptIn(ExperimentalMaterial3Api::class)
    fun `tooltip positions preserve logical and absolute directions`() {
        val positions =
            mapOf(
                "above" to TooltipAnchorPosition.Above,
                "below" to TooltipAnchorPosition.Below,
                "left" to TooltipAnchorPosition.Left,
                "right" to TooltipAnchorPosition.Right,
                "start" to TooltipAnchorPosition.Start,
                "end" to TooltipAnchorPosition.End,
            )
        positions.forEach { (wire, native) ->
            assertEquals(native, TooltipPropResolver.tooltipPosition(wire).getOrThrow())
        }
        assertTrue(TooltipPropResolver.tooltipPosition("invalid").isFailure)
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
        val valid =
            Json
                .parseToJsonElement(
                    """{"operations":[
                {"type":"padding","value":8},{"type":"padding","value":4},
                {"type":"clip","shape":"circle"}
            ]}""",
                ).jsonObject
        compose.setContent {
            assertTrue(builder.build(malformed).isFailure)
            for (size in listOf("1e39", "1e-50")) {
                val overflow =
                    Json
                        .parseToJsonElement(
                            """{"operations":[{"type":"size","width":$size,"height":8}]}""",
                        ).jsonObject
                assertTrue(builder.build(overflow).isFailure)
            }
            assertEquals(3, builder.build(valid).getOrThrow().foldIn(0) { count, _ -> count + 1 })
        }
    }
}
