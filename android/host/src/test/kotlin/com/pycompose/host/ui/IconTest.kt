package com.pycompose.host.ui

import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import com.pycompose.ir.IrParser
import com.pycompose.ir.ValidatedIr
import com.pycompose.renderer.ActionDispatcher
import com.pycompose.renderer.Renderer
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** The icon vocabulary: the app names an icon, the host resolves the pinned one. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34], application = android.app.Application::class)
class IconTest {
    @get:Rule val compose = createComposeRule()

    private fun parse(source: String): ValidatedIr = IrParser().parse(source).getOrThrow()

    /** ``description`` is a JSON value: the wire states text or an explicit null. */
    private fun icon(
        label: String,
        description: String,
    ): String =
        """{
            "version":"0.1.0","schemaVersion":"1.21.0",
            "root":{"id":"root","type":"Icon","props":{
                "imageVector":{"type":"materialIcon","name":"$label"},
                "contentDescription":$description
            }}
        }"""

    private fun renderer(): Renderer = Renderer(BuiltinComponents.registry(), ActionDispatcher {})

    @Test
    fun theAppNamesAnIconAndTheHostResolvesThePinnedOne() {
        // ``imageVector`` is an ``ImageVector`` the app cannot express, so the
        // wire carries the pinned icon's path under ``Icons`` and the generated
        // resolver reads that property. The description proves the call landed:
        // Compose reports exactly what the app stated.
        val ir = mutableStateOf(parse(icon("Filled.Add", "\"Add note\"")))
        compose.setContent { PyComposeTheme { renderer().Render(ir.value) } }

        compose.onNodeWithContentDescription("Add note").assertExists()
    }

    @Test
    fun aNewSnapshotSwapsTheIconAndItsDescription() {
        // A snapshot is resolved on every composition, so a label the app
        // changes reaches the native call without the app touching Kotlin.
        val ir = mutableStateOf(parse(icon("Filled.Add", "\"Add note\"")))
        compose.setContent { PyComposeTheme { renderer().Render(ir.value) } }

        compose.runOnIdle {
            ir.value = parse(icon("Filled.Info", "\"About this app\""))
        }
        compose.waitForIdle()

        compose.onNodeWithContentDescription("About this app").assertExists()
        compose.onNodeWithContentDescription("Add note").assertDoesNotExist()
    }

    @Test
    fun aNullDescriptionMarksTheIconDecorative() {
        // The pinned parameter is ``String?`` and takes no default, so the wire
        // states the null rather than a description being invented for it.
        val ir = mutableStateOf(parse(icon("Filled.Add", "null")))
        compose.setContent { PyComposeTheme { renderer().Render(ir.value) } }

        val described =
            compose
                .onAllNodes(
                    SemanticsMatcher.keyIsDefined(SemanticsProperties.ContentDescription),
                ).fetchSemanticsNodes()
        assertTrue(described.isEmpty())
    }
}
