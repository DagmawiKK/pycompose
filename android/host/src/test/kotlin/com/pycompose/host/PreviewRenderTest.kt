package com.pycompose.host

import androidx.compose.ui.test.junit4.createComposeRule
import com.pycompose.host.ui.BuiltinComponents
import com.pycompose.host.ui.PyComposeTheme
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
 * and accepted by Python's validator. Each renders here with the debug renderer;
 * an exception or any renderer report -- an unsupported type, a value that did
 * not resolve, an observation that could not attach -- fails that component.
 */
@RunWith(ParameterizedRobolectricTestRunner::class)
@Config(sdk = [34], application = android.app.Application::class)
class PreviewRenderTest(
    private val component: String,
) {
    @get:Rule val compose = createComposeRule()

    @Test
    fun theSampleRendersWithoutAReport() {
        val source = checkNotNull(javaClass.getResource("/previews/$component.json")).readText()
        val ir = IrParser().parse(source).getOrThrow()
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
    }

    companion object {
        @JvmStatic
        @ParameterizedRobolectricTestRunner.Parameters(name = "{0}")
        fun components(): List<Array<Any>> =
            checkNotNull(PreviewRenderTest::class.java.getResource("/previews/index.txt"))
                .readText()
                .lines()
                .filter { it.isNotBlank() }
                .map { arrayOf(it) }
    }
}
