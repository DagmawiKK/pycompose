package com.pycompose.host.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
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
 * The binding gate: every prop the pin can animate renders through its binding.
 *
 * `tools/previews.py` writes two snapshots per `(component, prop)` the lock
 * marks animatable: one at the target the catalog derives, one with the target
 * moved. Each pair is composed here, then the moved snapshot is stated as a
 * later frame, so the host reads the binding through the converter the pin
 * declares for that prop's type rather than merely passing a plain value.
 *
 * An exception, or any renderer report after either frame, fails that pair:
 * a binding the host cannot read is a capability the catalog claims and does
 * not have.
 */
@RunWith(ParameterizedRobolectricTestRunner::class)
@Config(sdk = [34], application = android.app.Application::class)
class BoundRenderTest(
    private val pair: String,
) {
    @get:Rule val compose = createComposeRule()

    @Test
    fun theBoundPropRendersAtItsTargetAndAfterTheTargetMoves() {
        val (first, then) = Samples.bindingFrames(pair)
        var ir by mutableStateOf(IrParser().parse(first).getOrThrow())
        val moved = IrParser().parse(then).getOrThrow()
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
        assertEquals("$pair at its stated target", emptyList<String>(), reports)

        // One snapshot states a new target; the host travels there on its clock.
        ir = moved
        compose.waitForIdle()
        assertEquals("$pair at its moved target", emptyList<String>(), reports)
    }

    companion object {
        @JvmStatic
        @ParameterizedRobolectricTestRunner.Parameters(name = "{0}")
        fun bindings(): List<Array<Any>> = Samples.bindings().map { arrayOf(it) }
    }
}
