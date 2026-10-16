package com.pycompose.host

import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.semantics.ProgressBarRangeInfo
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assertRangeInfoEquals
import androidx.compose.ui.test.junit4.createComposeRule
import com.pycompose.host.ui.BuiltinComponents
import com.pycompose.host.ui.PyComposeTheme
import com.pycompose.ir.IrParser
import com.pycompose.ir.ValidatedIr
import com.pycompose.renderer.ActionDispatcher
import com.pycompose.renderer.Renderer
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** The provider protocol: the app states a value, the host supplies the lambda. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34], application = android.app.Application::class)
class ProgressProviderTest {
    @get:Rule val compose = createComposeRule()

    private fun parse(source: String): ValidatedIr = IrParser().parse(source).getOrThrow()

    private fun indicator(progress: String): String =
        """{
            "version":"0.1.0","schemaVersion":"1.20.0",
            "root":{"id":"root","type":"LinearProgressIndicator","props":{
                "progress":$progress
            }}
        }"""

    private fun renderer(): Renderer = Renderer(BuiltinComponents.registry(), ActionDispatcher {})

    @Test
    fun theAppStatesAProgressValueAndTheHostProvidesTheLambda() {
        // The pinned parameter is `progress: () -> Float`, which the app cannot
        // name. The generated adapter supplies a lambda reading the current
        // snapshot, so Compose reports exactly what the app stated.
        val ir = mutableStateOf(parse(indicator("0.25")))
        compose.setContent { PyComposeTheme { renderer().Render(ir.value) } }

        compose
            .onNode(SemanticsMatcher.keyIsDefined(SemanticsProperties.ProgressBarRangeInfo))
            .assertRangeInfoEquals(ProgressBarRangeInfo(0.25f, 0f..1f))
    }

    @Test
    fun aNewSnapshotMovesTheProvidedValue() {
        // The lambda is re-supplied on every composition, so a value the app
        // changes reaches the native call without the app touching Kotlin.
        val ir = mutableStateOf(parse(indicator("0.25")))
        compose.setContent { PyComposeTheme { renderer().Render(ir.value) } }

        compose.runOnIdle { ir.value = parse(indicator("0.75")) }
        compose.waitForIdle()
        compose
            .onNode(SemanticsMatcher.keyIsDefined(SemanticsProperties.ProgressBarRangeInfo))
            .assertRangeInfoEquals(ProgressBarRangeInfo(0.75f, 0f..1f))
    }

    @Test
    fun anOutOfRangeValueKeepsThePinnedCoercion() {
        // PyCompose states the value, not the bounds: the component's own
        // ``coerceIn(0f, 1f)`` remains the only clamp, so nothing is silently
        // narrowed twice.
        val ir = mutableStateOf(parse(indicator("1.5")))
        compose.setContent { PyComposeTheme { renderer().Render(ir.value) } }

        compose
            .onNode(SemanticsMatcher.keyIsDefined(SemanticsProperties.ProgressBarRangeInfo))
            .assertRangeInfoEquals(ProgressBarRangeInfo(1f, 0f..1f))
    }
}
