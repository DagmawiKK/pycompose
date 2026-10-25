package com.pycompose.host

import android.graphics.Bitmap
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.semantics.SemanticsNode
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.semantics.getOrNull
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.isRoot
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onRoot
import com.pycompose.host.ui.BuiltinComponents
import com.pycompose.host.ui.PyComposeTheme
import com.pycompose.ir.IrParser
import com.pycompose.renderer.ActionDispatcher
import com.pycompose.renderer.Renderer
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.ParameterizedRobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import java.io.File

/**
 * Device-free rendering for `pycompose render` (plan 31 §18.7): an app's own
 * snapshots, drawn by its own generated host on the JVM.
 *
 * `-PpycomposeRender=<request.json>` names the snapshots and where the results
 * go. Each renders in a phone-sized frame and writes a PNG and a semantics dump
 * -- what accessibility services and tests read: roles, texts, descriptions,
 * actions and bounds, for every window. Without a request it renders nothing.
 */
@RunWith(ParameterizedRobolectricTestRunner::class)
@Config(
    sdk = [34],
    application = android.app.Application::class,
    qualifiers = "w360dp-h640dp-xhdpi",
)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class RenderSnapshots(
    private val name: String,
    private val path: String,
    private val out: String,
) {
    @get:Rule val compose = createComposeRule()

    @Test
    fun theSnapshotIsRendered() {
        val ir = IrParser().parse(File(path).readText()).getOrThrow()
        val reports = mutableListOf<String>()
        val renderer =
            Renderer(
                BuiltinComponents.registry(),
                ActionDispatcher {},
                debug = true,
            ) { reports.add(it) }
        val directory = File(out).apply { mkdirs() }
        // A sample that throws is that sample's report, not the run's failure:
        // the caller decides what a report means (`pycompose add` refuses it).
        val windows =
            runCatching {
                compose.setContent {
                    PyComposeTheme {
                        Box(Modifier.fillMaxSize().background(Color.White)) { renderer.Render(ir) }
                    }
                }
                compose.waitForIdle()
                val image = compose.onRoot().captureToImage().asAndroidBitmap()
                File(directory, "$name.png").outputStream().use {
                    image.compress(Bitmap.CompressFormat.PNG, 100, it)
                }
                compose.onAllNodes(isRoot()).fetchSemanticsNodes().map(::describe)
            }.getOrElse { failure ->
                reports.add("throws ${failure::class.java.simpleName}: ${failure.message}")
                emptyList()
            }
        val dump =
            buildJsonObject {
                put("windows", JsonArray(windows))
                put("reports", JsonArray(reports.map(::JsonPrimitive)))
            }
        File(directory, "$name.semantics.json").writeText(dump.toString())
    }

    private fun describe(node: SemanticsNode): JsonElement =
        buildJsonObject {
            val config = node.config
            config.getOrNull(SemanticsProperties.Role)?.let { put("role", it.toString()) }
            config.getOrNull(SemanticsProperties.Text)?.let { texts ->
                put("text", buildJsonArray { texts.forEach { add(JsonPrimitive(it.text)) } })
            }
            config.getOrNull(SemanticsProperties.ContentDescription)?.let { descriptions ->
                put(
                    "contentDescription",
                    buildJsonArray { descriptions.forEach { add(JsonPrimitive(it)) } },
                )
            }
            config.getOrNull(SemanticsProperties.EditableText)?.let { put("editableText", it.text) }
            config.getOrNull(SemanticsProperties.TestTag)?.let { put("testTag", it) }
            val actions = config.map { it.key.name }.filter { it.first().isUpperCase() }
            put(
                "properties",
                buildJsonArray { actions.sorted().forEach { add(JsonPrimitive(it)) } },
            )
            val bounds = node.boundsInRoot
            put(
                "bounds",
                buildJsonArray {
                    listOf(
                        bounds.left,
                        bounds.top,
                        bounds.right,
                        bounds.bottom,
                    ).forEach { add(JsonPrimitive(it)) }
                },
            )
            put("children", JsonArray(node.children.map(::describe)))
        }

    companion object {
        @JvmStatic
        @ParameterizedRobolectricTestRunner.Parameters(name = "{0}")
        fun snapshots(): List<Array<Any>> {
            val request = System.getProperty("pycompose.render") ?: return emptyList()
            val document = Json.parseToJsonElement(File(request).readText()).jsonObject
            val out = document.getValue("out").jsonPrimitive.content
            return document.getValue("snapshots").jsonArray.map {
                val snapshot = it as JsonObject
                arrayOf(
                    snapshot.getValue("name").jsonPrimitive.content,
                    snapshot.getValue("path").jsonPrimitive.content,
                    out,
                )
            }
        }
    }
}
