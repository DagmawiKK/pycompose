package com.pycompose.host.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.toPixelMap
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onRoot
import com.pycompose.ir.IrParser
import com.pycompose.ir.ValidatedIr
import com.pycompose.renderer.ActionDispatcher
import com.pycompose.renderer.Renderer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

/**
 * Behaviour as data (plan 31 §6): a scrim colour follows the drawer's open fraction.
 *
 * The app states only an expression -- `alpha(#FF0000, progress)` over the
 * drawer's own stream -- and the host evaluates it as the drawer moves, so the
 * scrim tracks the drawer with no Python in the loop.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34], application = android.app.Application::class, qualifiers = "w360dp-h640dp-mdpi")
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class StreamExpressionTest {
    @get:Rule val compose = createComposeRule()

    private fun snapshot(open: Boolean) =
        IrParser()
            .parse(
                """
                {"version":"0.1.0","schemaVersion":"1.23.0","root":{"id":"nav","type":"ModalNavigationDrawer",
                  "props":{"open":$open,"scrimColor":{"type":"expression","node":{"op":"alpha",
                    "color":"#FFFF0000","args":[{"stream":"nav","name":"progress"}]}}},
                  "children":[
                    {"id":"menu","type":"Text","slot":"drawer","props":{"text":"Menu"}},
                    {"id":"body","type":"Text","props":{"text":"Body"}}]}}
                """.trimIndent(),
            ).getOrThrow()

    private fun renderer(reports: MutableList<String>) =
        Renderer(
            BuiltinComponents.registry(),
            ActionDispatcher {},
            debug = true,
            report = { reports.add(it) },
        )

    /** The colour at the right edge, where the scrim covers the content when open. */
    private fun edge() =
        compose.onRoot().captureToImage().toPixelMap().let {
            it[
                it.width - 4, it.height /
                    2,
            ]
        }

    private fun Color.isScrimRed() = red > 0.9f && green < 0.1f && blue < 0.1f

    @Test
    fun theScrimFollowsTheDrawersMeasuredOpenFraction() {
        val reports = mutableListOf<String>()
        val renderer = renderer(reports)
        var ir by mutableStateOf(snapshot(open = false))
        compose.setContent { PyComposeTheme { renderer.Render(ir) } }
        compose.waitForIdle()
        // Closed and at rest: the drawer's travel is measured, the scrim is clear.
        assertFalse("closed scrim is clear: ${edge()}", edge().isScrimRed())

        ir = snapshot(open = true)
        compose.mainClock.advanceTimeBy(2_000)
        compose.waitForIdle()
        // Open: progress, measured against that travel, is 1 -- the expression's red.
        assertTrue("open scrim is red: ${edge()}", edge().isScrimRed())
        assertEquals(emptyList<String>(), reports)
    }

    private fun scrolled(offset: Double): ValidatedIr {
        val rows =
            (0 until 40).joinToString(",") {
                """{"id":"row$it","type":"Text","props":{"text":"Row $it"}}"""
            }
        val dp = """{"type":"Dp","value":"""
        val size = """{"type":"size","width":${dp}360},"height":${dp}200}}"""
        return IrParser()
            .parse(
                """
                {"version":"0.1.0","schemaVersion":"1.23.0","root":{"id":"page","type":"Column","props":{},
                  "children":[
                    {"id":"band","type":"Surface","props":{"modifier":{"operations":[$size]},
                      "color":{"type":"expression","node":{"op":"mix","colors":["#FFFFFFFF","#FF0000FF"],
                        "args":[{"stream":"list","name":"progress"}]}}}},
                    {"id":"list","type":"Column","props":{"scrollable":true,"offset":$offset,
                      "modifier":{"operations":[$size]}},"children":[$rows]}]}}
                """.trimIndent(),
            ).getOrThrow()
    }

    /** The colour inside the band the expression paints. */
    private fun band() =
        compose
            .onRoot()
            .captureToImage()
            .toPixelMap()
            .let { it[it.width / 2, 20] }

    @Test
    fun aColourFollowsAScrollsProgress() {
        val reports = mutableListOf<String>()
        val renderer = renderer(reports)
        var ir by mutableStateOf(scrolled(0.0))
        compose.setContent { PyComposeTheme { renderer.Render(ir) } }
        compose.waitForIdle()
        // At the top: progress 0, the mix's start.
        assertTrue("top is white: ${band()}", band().blue > 0.9f && band().red > 0.9f)

        ir = scrolled(100_000.0)
        compose.mainClock.advanceTimeBy(2_000)
        compose.waitForIdle()
        // Scrolled to the end: progress 1, the mix's stop.
        assertTrue("end is blue: ${band()}", band().blue > 0.9f && band().red < 0.1f)
        assertEquals(emptyList<String>(), reports)
    }
}
