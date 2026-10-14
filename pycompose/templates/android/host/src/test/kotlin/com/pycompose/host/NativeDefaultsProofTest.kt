package com.pycompose.host

import androidx.compose.foundation.layout.Column
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.LocalTextStyle
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performSemanticsAction
import androidx.compose.ui.text.TextLayoutResult
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.unit.sp
import com.pycompose.renderer.PropResolver
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** Compile/behavior proof only: no new component or public wire contract. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34], application = android.app.Application::class)
class NativeDefaultsProofTest {
    @get:Rule val compose = createComposeRule()

    @Test fun suppliedValuesReachComposeAndMissingValuesKeepContextualDefaults() {
        val props = mutableStateOf(JsonObject(emptyMap()))
        compose.setContent {
            MaterialTheme {
                CompositionLocalProvider(
                    LocalTextStyle provides TextStyle(fontSize = 27.sp),
                    LocalContentColor provides Color.Magenta,
                ) {
                    Column {
                        NativeTextDefaults("Adapter", props.value)
                        Text("Reference")
                    }
                }
            }
        }
        val reference = layout("Reference").layoutInput
        val omitted = layout("Adapter").layoutInput
        assertEquals(reference.maxLines, omitted.maxLines)
        assertEquals(reference.softWrap, omitted.softWrap)
        assertEquals(reference.style.color, omitted.style.color)
        assertEquals(reference.style.fontSize, omitted.style.fontSize)
        assertEquals(Color.Magenta, omitted.style.color)
        assertEquals(27.sp, omitted.style.fontSize)

        compose.runOnIdle {
            props.value =
                JsonObject(
                    mapOf(
                        "maxLines" to JsonPrimitive(1),
                        "minLines" to JsonPrimitive(1),
                        "softWrap" to JsonPrimitive(false),
                        "color" to JsonPrimitive("#FF0000FF"),
                    ),
                )
        }
        val supplied = layout("Adapter").layoutInput
        assertEquals(1, supplied.maxLines)
        assertEquals(false, supplied.softWrap)
        assertEquals(Color.Blue, supplied.style.color)
        val oneLineHeight = layout("Adapter").size.height
        compose.runOnIdle {
            props.value =
                JsonObject(
                    mapOf("minLines" to JsonPrimitive(3), "maxLines" to JsonPrimitive(5)),
                )
        }
        assertTrue(layout("Adapter").size.height > oneLineHeight)
    }

    @Test fun nullableCallbackAcceptsProvidedNullAndMissingWithoutReplay() {
        val props = mutableStateOf(JsonObject(mapOf("onTextLayout" to JsonPrimitive("capture"))))
        val reports = mutableListOf<String>()
        compose.setContent {
            MaterialTheme {
                NativeTextDefaults("Adapter", props.value) { reports.add("capture") }
            }
        }
        compose.waitForIdle()
        assertTrue(reports.isNotEmpty())
        compose.runOnIdle {
            reports.clear()
            props.value =
                JsonObject(mapOf("onTextLayout" to JsonNull, "maxLines" to JsonPrimitive(2)))
        }
        compose.waitForIdle()
        assertTrue(reports.isEmpty())
        compose.runOnIdle {
            props.value = JsonObject(mapOf("maxLines" to JsonPrimitive(3)))
        }
        compose.waitForIdle()
        assertTrue(reports.isEmpty())
    }

    private fun layout(text: String): TextLayoutResult {
        val results = mutableListOf<TextLayoutResult>()
        compose.onNodeWithText(text).performSemanticsAction(SemanticsActions.GetTextLayoutResult) {
            it(results)
        }
        return results.single()
    }
}

/**
 * A single native call with linear default resolution, not 2^N omission branches.
 * The defaults below were verified against commonMain/androidx/compose/material3/Text.kt
 * in Google's material3-android:1.3.1 sources JAR. This is deliberately test-scoped:
 * extracting default providers for the rest of the catalog is still separate work.
 */
@Composable
private fun NativeTextDefaults(
    text: String,
    props: JsonObject,
    onLayout: ((TextLayoutResult) -> Unit)? = null,
) {
    val callback =
        when (val binding = props["onTextLayout"]) {
            null, JsonNull -> null
            else -> {
                require(binding.jsonPrimitive.content == "capture")
                requireNotNull(onLayout)
            }
        }
    val color =
        props["color"]?.jsonPrimitive?.content?.let { PropResolver.color(it).getOrThrow() }
            ?: Color.Unspecified
    Text(
        text = text,
        maxLines = props["maxLines"]?.jsonPrimitive?.int ?: Int.MAX_VALUE,
        minLines = props["minLines"]?.jsonPrimitive?.int ?: 1,
        softWrap = props["softWrap"]?.jsonPrimitive?.boolean ?: true,
        color = color,
        style = LocalTextStyle.current,
        onTextLayout = callback,
    )
}
