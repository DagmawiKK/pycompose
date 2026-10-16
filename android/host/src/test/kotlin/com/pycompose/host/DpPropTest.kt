package com.pycompose.host

import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import com.pycompose.host.ui.BuiltinComponents
import com.pycompose.host.ui.PyComposeTheme
import com.pycompose.ir.IrParser
import com.pycompose.ir.ValidatedIr
import com.pycompose.renderer.ActionDispatcher
import com.pycompose.renderer.Renderer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/**
 * Density-independent props: a bare number on the wire means dp.
 *
 * The app states a number and the host reads it in the unit the app stated, not
 * in pixels; an absent one keeps the pinned default rather than becoming zero.
 * The screen renders at xhdpi, so a number mistaken for pixels would be half the
 * height the assertions expect on purpose.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34], qualifiers = "xhdpi", application = android.app.Application::class)
class DpPropTest {
    @get:Rule val compose = createComposeRule()

    private fun parse(source: String): ValidatedIr = IrParser().parse(source).getOrThrow()

    private fun renderer(): Renderer = Renderer(BuiltinComponents.registry(), ActionDispatcher {})

    /** Two texts with a divider between them, whose thickness is stated or not. */
    private fun screen(thickness: Int?): String {
        val stated = if (thickness == null) "" else """"thickness":$thickness"""
        return """
            {"version":"0.1.0","schemaVersion":"1.22.0",
             "root":{"id":"root","type":"Column","props":{},"children":[
               {"id":"root.above","type":"Text","props":{"text":"Above"}},
               {"id":"root.divider","type":"HorizontalDivider","props":{$stated}},
               {"id":"root.below","type":"Text","props":{"text":"Below"}}]}}
            """.trimIndent()
    }

    /** The divider's laid-out height in pixels, read from the gap it opens. */
    private fun gapPx(): Float =
        compose
            .onNodeWithText("Below")
            .fetchSemanticsNode()
            .boundsInRoot.top -
            compose
                .onNodeWithText("Above")
                .fetchSemanticsNode()
                .boundsInRoot.bottom

    @Test
    fun aStatedThicknessIsReadAsDensityIndependentPixels() {
        var density = 0f
        val ir = mutableStateOf(parse(screen(thickness = 12)))
        compose.setContent {
            density = LocalDensity.current.density
            PyComposeTheme { renderer().Render(ir.value) }
        }
        assertEquals(2f, density, 0.01f)

        val stated = gapPx()
        assertEquals(12f * density, stated, 0.01f)

        // Silence is not zero: the adapter names the pinned default, so the
        // divider still draws a hairline instead of collapsing.
        compose.runOnIdle { ir.value = parse(screen(thickness = null)) }
        compose.waitForIdle()
        val pinned = gapPx()
        assertEquals(1f * density, pinned, 0.01f)
        assertTrue("expected $stated > $pinned", stated > pinned)
    }
}
