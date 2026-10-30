package com.pycompose.host.ui

import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.semantics.SemanticsNode
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.semantics.getOrNull
import androidx.compose.ui.test.isRoot
import androidx.compose.ui.test.junit4.createComposeRule
import com.pycompose.ir.IrParser
import com.pycompose.renderer.ActionDispatcher
import com.pycompose.renderer.Renderer
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.ParameterizedRobolectricTestRunner
import org.robolectric.annotation.Config

/**
 * The render gate (plan 31 §10): every catalog component composes on the JVM.
 *
 * `tools/previews.py` writes one sample per component, built from its types
 * and accepted by Python's validator ([Samples]). Each renders here with the debug renderer;
 * an exception or any renderer report -- an unsupported type, a value that did
 * not resolve, an observation that could not attach -- fails that component.
 *
 * The semantics gate (plan 31 §16.6) runs on the same render: every element a
 * user can act on announces a label -- its text, its edited text, or a
 * content description. A control with no text of its own takes one from the
 * `semantics` modifier, as the sample does.
 */
@RunWith(ParameterizedRobolectricTestRunner::class)
@Config(sdk = [34], application = android.app.Application::class)
class PreviewRenderTest(
    private val component: String,
) {
    @get:Rule val compose = createComposeRule()

    @Test
    fun theSampleRendersWithoutAReport() {
        val ir = IrParser().parse(Samples.source(component)).getOrThrow()
        val reports = mutableListOf<String>()
        val renderer =
            Renderer(
                BuiltinComponents.registry(),
                ActionDispatcher {},
                debug = true,
                report = { reports.add(it) },
            )
        compose.setContent { PyComposeTheme { renderer.Render(ir) } }
        compose.waitForIdle()
        assertEquals(emptyList<String>(), reports)
        val unlabelled = mutableListOf<String>()

        fun visit(node: SemanticsNode) {
            if (node.isInteractive() && !node.isLabelled()) unlabelled.add(node.config.toString())
            node.children.forEach(::visit)
        }
        // A dialog or popup composes in a window of its own: one root each.
        compose.onAllNodes(isRoot()).fetchSemanticsNodes().forEach(::visit)
        assertEquals("interactive elements without a label", emptyList<String>(), unlabelled)
    }

    private fun SemanticsNode.isInteractive() =
        SemanticsActions.OnClick in config ||
            SemanticsActions.SetProgress in config ||
            SemanticsActions.SetText in config ||
            SemanticsProperties.ToggleableState in config

    private fun SemanticsNode.isLabelled() =
        !config.getOrNull(SemanticsProperties.Text).isNullOrEmpty() ||
            !config.getOrNull(SemanticsProperties.ContentDescription).isNullOrEmpty() ||
            SemanticsProperties.EditableText in config

    companion object {
        @JvmStatic
        @ParameterizedRobolectricTestRunner.Parameters(name = "{0}")
        fun components(): List<Array<Any>> = Samples.names().map { arrayOf(it) }
    }
}
