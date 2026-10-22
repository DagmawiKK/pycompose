package com.pycompose.renderer

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.test.junit4.createComposeRule
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** The projection protocol every [Reconcile] family shares, proven once on a stand-in holder. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class ReconcileTest {
    @get:Rule val compose = createComposeRule()

    /** A native holder stand-in: its value moves through drives or simulated gestures. */
    private class Holder {
        var value by mutableStateOf("closed")
        val drives = mutableListOf<String>()
    }

    private val holder = Holder()
    private var desired by mutableStateOf<String?>(null)
    private var reporting by mutableStateOf(true)
    private var tick by mutableStateOf(0)
    private val reports = mutableListOf<String>()

    private fun start() {
        compose.setContent {
            tick // Recompose on demand without changing the desired value.
            Reconcile(
                holder,
                desired,
                remember(holder) { mutableStateOf<String?>(null) },
                settled = { holder.value },
                report = if (reporting) ({ reports += it }) else null,
            ) {
                holder.drives += it
                holder.value = it
            }
        }
        compose.waitForIdle()
    }

    private fun act(change: () -> Unit) {
        compose.runOnIdle(change)
        compose.waitForIdle()
    }

    @Test
    fun theStartingValueIsNeitherDrivenNorReported() {
        start()
        assertEquals(emptyList<String>(), holder.drives)
        assertEquals(emptyList<String>(), reports)
    }

    @Test
    fun aChangedDesireDrivesOnceAndItsSettleIsReportedOnce() {
        start()
        act { desired = "open" }
        act { tick++ }
        assertEquals(listOf("open"), holder.drives)
        assertEquals(listOf("open"), reports)
    }

    @Test
    fun aNativeSettleIsReportedAndTheAppsEchoDoesNotDriveIt() {
        start()
        act { holder.value = "open" }
        act { desired = "open" }
        assertEquals(emptyList<String>(), holder.drives)
        assertEquals(listOf("open"), reports)
    }

    @Test
    fun anUnchangedDesireNeverFightsAGesture() {
        start()
        act { desired = "open" }
        act { holder.value = "closed" }
        act { tick++ }
        assertEquals(listOf("open"), holder.drives)
        assertEquals(listOf("open", "closed"), reports)
    }

    @Test
    fun withoutAReportTheHolderIsStillDrivenButSilent() {
        reporting = false
        start()
        act { desired = "open" }
        assertEquals(listOf("open"), holder.drives)
        assertEquals(emptyList<String>(), reports)
    }
}
