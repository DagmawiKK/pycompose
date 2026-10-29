package com.pycompose.proof

import androidx.compose.foundation.layout.Column
import androidx.compose.material3.Button
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.Composable
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.text.TextLayoutResult
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** Test-only calls generated from pinned metadata. No production catalog changes. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class GeneratedCallsProof {
    @get:Rule val compose = createComposeRule()

    private fun props(value: String) = Json.parseToJsonElement(value) as JsonObject

    @Test fun suppliedScalarsAndAbsentDefaultsMatchDirectTextAcrossThemes() {
        val dark = mutableStateOf(false)
        compose.setContent {
            MaterialTheme(colorScheme = if (dark.value) darkColorScheme() else lightColorScheme()) {
                Column {
                    CALL_Text(props("""{"text":"native text","maxLines":2,"minLines":1,"softWrap":false}"""), Modifier.testTag("generated"))
                    Text("native text", Modifier.testTag("direct"), maxLines = 2, minLines = 1, softWrap = false)
                    CALL_Text(props("""{"text":"native text","fontSize":{"type":"Sp","value":30}}"""), Modifier.testTag("supplied"))
                }
            }
        }
        repeat(2) {
            compose.runOnIdle {
                fun layout(tag: String): TextLayoutResult {
                    val results = mutableListOf<TextLayoutResult>()
                    compose.onNodeWithTag(tag).fetchSemanticsNode().config[SemanticsActions.GetTextLayoutResult].action!!.invoke(results)
                    return results.single()
                }
                val generated = layout("generated").layoutInput
                val direct = layout("direct").layoutInput
                assertEquals(direct.style, generated.style)
                assertEquals(direct.maxLines, generated.maxLines)
                assertEquals(direct.softWrap, generated.softWrap)
                assertTrue(layout("supplied").layoutInput.style.fontSize.value > generated.style.fontSize.value)
                dark.value = true
            }
            compose.waitForIdle()
        }
    }

    @Test fun scopedContentUsesComposeDefaultsAndClickDispatchesJson() {
        val events = mutableListOf<Pair<String, JsonElement>>()
        val dark = mutableStateOf(false)
        var generated = Color.Unspecified
        var direct = Color.Unspecified
        compose.setContent {
            MaterialTheme(colorScheme = if (dark.value) darkColorScheme() else lightColorScheme()) {
                Column {
                    CALL_Button(props("""{"onClick":"tap"}"""), dispatch = { id, payload -> events.add(id to payload) }, slot_content = {
                        val color = LocalContentColor.current
                        SideEffect { generated = color }
                        Text("generated button", Modifier.weight(1f, fill = false))
                    })
                    Button(onClick = {}) {
                        val color = LocalContentColor.current
                        SideEffect { direct = color }
                        Text("direct button")
                    }
                    CALL_Button(props("""{"onClick":"flat","elevation":null}"""), slot_content = { Text("null elevation") })
                }
            }
        }
        compose.onNodeWithText("generated button").performClick()
        compose.runOnIdle { assertEquals(direct, generated); assertEquals("tap", events.single().first); dark.value = true }
        compose.waitForIdle()
        compose.runOnIdle { assertEquals(direct, generated) }
    }

    @Test fun nullableCallbackAndBooleanPayloadStayDistinct() {
        val events = mutableListOf<Pair<String, JsonElement>>()
        compose.setContent {
            Column {
                CALL_Switch(props("""{"checked":false,"onCheckedChange":"toggle"}"""), Modifier.testTag("active"), { id, payload -> events.add(id to payload) })
                CALL_Switch(props("""{"checked":true,"onCheckedChange":null}"""), Modifier.testTag("readonly"))
            }
        }
        compose.onNodeWithTag("active").performClick()
        compose.runOnIdle { assertEquals(listOf("toggle" to JsonPrimitive(true)), events) }
    }

    @Test fun independentNamedSlotsAndAbsentNullableSlotsRender() {
        compose.setContent {
            CALL_AlertDialog(props("""{"onDismissRequest":"dismiss"}"""), slot_confirmButton = { Text("confirm slot") }, slot_title = { Text("title slot") })
        }
        compose.onNodeWithText("confirm slot").assertExists()
        compose.onNodeWithText("title slot").assertExists()
    }

    @Test fun multiFieldEventsAreAtomicAndNativeModifierIsNotInvented() {
        val events = mutableListOf<JsonElement>()
        compose.setContent {
            Column {
                CALL_Probe(props("""{"onReport":"report"}"""), dispatch = { _, payload -> events.add(payload) }, slot_content = { Text("defaults") })
                CALL_Probe(props("""{"onReport":"report","first":9,"second":false,"onCancel":null}"""), dispatch = { _, payload -> events.add(payload) }, slot_content = { Text("supplied") })
            }
        }
        compose.onNodeWithText("defaults").performClick()
        compose.onNodeWithText("supplied").performClick()
        compose.runOnIdle {
            assertEquals(listOf(props("""{"arg0":3,"arg1":"yes"}"""), props("""{"arg0":9,"arg1":null}""")), events)
        }
    }

    @Test fun representableFloatPropReachesCompose() {
        compose.setContent {
            CALL_Probe(props("""{"onReport":"report","ratio":0.5}"""), slot_content = { Text("in range") })
        }
        compose.onNodeWithText("in range").assertExists()
    }

    @Test fun floatOverflowIsRefusedBeforeCompose() {
        assertTrue("1e308 must not narrow to Infinity", refusalOf("1e308") is IllegalArgumentException)
    }

    @Test fun floatUnderflowIsRefusedBeforeCompose() {
        assertTrue("1e-60 must not narrow to zero", refusalOf("1e-60") is IllegalArgumentException)
    }

    /** Compose a probe whose float prop the decoder must refuse, and report why. */
    private fun refusalOf(ratio: String): Throwable? = try {
        compose.setContent {
            CALL_Probe(props("""{"onReport":"report","ratio":$ratio}"""), slot_content = { Text("unreachable") })
        }
        null
    } catch (error: Throwable) {
        error
    }
}

/** An independent signature fixture exercises policies not paired in pinned M3. */
@Composable
fun PolicyProbe(
    first: Int = 3,
    second: Boolean = true,
    ratio: Float = 1.5f,
    onReport: (Int, String?) -> Unit,
    onCancel: (() -> Unit)? = null,
    content: @Composable () -> Unit,
) {
    Button(onClick = { onReport(first, if (second) "yes" else null); onCancel?.invoke() }) { content() }
}
