package com.pycompose.host.ui

import androidx.compose.runtime.Recomposer
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.snapshots.Snapshot
import androidx.compose.ui.test.junit4.createComposeRule
import com.pycompose.ir.IrParser
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
 * A binding read in layout or draw animates with no recomposition anywhere; one read in
 * composition recomposes as it travels. Each snapshot is the one Python emits, rendered by the
 * generated adapters and modifiers, and the count is the recomposer's own: every frame that
 * recomposes anything moves it.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34], application = android.app.Application::class)
class BindingPhaseTest {
    @get:Rule val compose = createComposeRule()

    private fun travel(
        target: String,
        phase: String,
    ) = """{"type":"binding","target":$target,"travel":
           {"kind":"tween","durationMs":300,"delayMs":0},"phase":"$phase"}"""

    private fun snapshot(root: String) =
        IrParser()
            .parse("""{"version":"0.1.0","schemaVersion":"1.23.0","root":{"id":"root",$root}}""")
            .getOrThrow()

    private fun box(operation: String) =
        """"type":"Box","props":{"modifier":{"operations":[$operation]}}"""

    private fun changes(): Long = Recomposer.runningRecomposers.value.sumOf { it.changeCount }

    /** How many recompositions ten frames of travel cost, after the snapshot that starts it. */
    private fun travelling(root: (Int) -> String): Long {
        val ir = mutableStateOf(snapshot(root(0)))
        compose.mainClock.autoAdvance = false
        compose.setContent {
            PyComposeTheme {
                Renderer(
                    BuiltinComponents.registry(),
                    ActionDispatcher {},
                ).Render(ir.value)
            }
        }
        compose.mainClock.advanceTimeBy(FRAME * 4)
        ir.value = snapshot(root(1))
        Snapshot.sendApplyNotifications()
        // The new snapshot recomposes once, and the travel starts.
        repeat(2) { compose.mainClock.advanceTimeByFrame() }
        val before = changes()
        repeat(10) { compose.mainClock.advanceTimeByFrame() }
        return changes() - before
    }

    @Test
    fun aDrawPhaseModifierArgumentTravelsWithNoRecomposition() {
        val recompositions =
            travelling { step ->
                box(
                    """{"type":"graphicsLayer","alpha":${travel(
                        if (step == 0) "0.2" else "1.0",
                        "draw",
                    )}}""",
                )
            }
        assertEquals(0L, recompositions)
    }

    @Test
    fun aLayoutPhaseModifierArgumentTravelsWithNoRecomposition() {
        val recompositions =
            travelling { step ->
                box("""{"type":"offset","x":${travel(if (step == 0) "0" else "80", "layout")}}""")
            }
        assertEquals(0L, recompositions)
    }

    @Test
    fun aProducedColourTravelsWithNoRecomposition() {
        val recompositions =
            travelling { step ->
                val colour = if (step == 0) "4278190080" else "4284960932"
                """"type":"BasicText","props":{"text":{"type":"AnnotatedString","text":"Hi"},
                   "color":${travel("""{"type":"Color","color":$colour}""", "draw")}}"""
            }
        assertEquals(0L, recompositions)
    }

    @Test
    fun aProvidedProgressTravelsWithNoRecomposition() {
        val recompositions =
            travelling { step ->
                """"type":"LinearProgressIndicator","props":
                   {"progress":${travel(if (step == 0) "0.1" else "0.9", "draw")}}"""
            }
        assertEquals(0L, recompositions)
    }

    @Test
    fun aCompositionPhaseArgumentRecomposesAsItTravels() {
        val recompositions =
            travelling { step ->
                box(
                    """{"type":"alpha","alpha":${travel(
                        if (step == 0) "0.2" else "1.0",
                        "composition",
                    )}}""",
                )
            }
        assertTrue(
            "a composition read recomposes per frame, not $recompositions",
            recompositions >= 8,
        )
    }

    private companion object {
        const val FRAME = 16L
    }
}
