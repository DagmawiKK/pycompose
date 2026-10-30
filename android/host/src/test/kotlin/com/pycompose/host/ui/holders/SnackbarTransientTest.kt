package com.pycompose.host.ui.holders

import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.junit4.StateRestorationTester
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import com.pycompose.host.SessionSnapshot
import com.pycompose.host.intent
import com.pycompose.host.ui.BuiltinComponents
import com.pycompose.host.ui.PyComposeTheme
import com.pycompose.ir.IrParser
import com.pycompose.ir.ValidatedIr
import com.pycompose.renderer.Action
import com.pycompose.renderer.ActionDispatcher
import com.pycompose.renderer.Renderer
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** The transient wire end to end: a serial-numbered request the host fulfils. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class SnackbarTransientTest {
    @get:Rule val compose = createComposeRule()

    @Test
    fun aSerialShowsOnceItsActionAnswersAndAnIdenticalSnapshotChangesNothing() {
        // The serial is the whole protocol: the request shows, the action
        // fulfils it and the occurrence reports the serial back; re-stating
        // the identical request is a no-op, not a second show.
        val ir = mutableStateOf(parse(host(serial = 1)))
        val actions = mutableListOf<Action>()
        compose.setContent { PyComposeTheme { renderer(actions).Render(ir.value) } }

        compose.waitUntil(
            5000,
        ) { compose.onAllNodesWithText("Saved").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithText("Undo").performClick()
        compose.waitUntil(5000) { actions.isNotEmpty() }
        assertEquals(intent("demo.dismiss"), actions[0].actionId)
        assertEquals(JsonPrimitive(1L), actions[0].payload["serial"])

        compose.runOnIdle { ir.value = parse(host(serial = 1)) }
        compose.waitForIdle()

        assertTrue(actions.size == 1)
        compose.onNodeWithText("Saved").assertDoesNotExist()
    }

    @Test
    fun aBumpedSerialShowsTheRequestAgain() {
        // A new serial is a new request: the host shows it once, and its
        // fulfilment reports the new serial over the old one.
        val ir = mutableStateOf(parse(host(serial = 1)))
        val actions = mutableListOf<Action>()
        compose.setContent { PyComposeTheme { renderer(actions).Render(ir.value) } }
        compose.waitUntil(
            5000,
        ) { compose.onAllNodesWithText("Saved").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithText("Undo").performClick()
        compose.waitUntil(5000) { actions.isNotEmpty() }

        compose.runOnIdle { ir.value = parse(host(serial = 2)) }

        compose.waitUntil(
            5000,
        ) { compose.onAllNodesWithText("Saved").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithText("Undo").performClick()
        compose.waitUntil(5000) { actions.size == 2 }
        assertEquals(JsonPrimitive(2L), actions[1].payload["serial"])
    }

    @Test
    fun anOlderSerialCannotCancelAnInFlightRequest() {
        val ir = mutableStateOf(parse(host(serial = 10)))
        val actions = mutableListOf<Action>()
        compose.setContent { PyComposeTheme { renderer(actions).Render(ir.value) } }
        compose.waitForIdle()
        compose.onNodeWithText("Saved").assertExists()

        compose.runOnIdle { ir.value = parse(host(serial = 9, message = "Stale")) }
        compose.waitForIdle()

        compose.onNodeWithText("Saved").assertExists()
        compose.onNodeWithText("Stale").assertDoesNotExist()
        compose.onNodeWithText("Undo").performClick()
        compose.waitUntil(5000) { actions.isNotEmpty() }
        assertEquals(JsonPrimitive(10L), actions.single().payload["serial"])
    }

    @Test
    fun changingContentAtTheSameSerialDoesNotRestartTheRequest() {
        val ir = mutableStateOf(parse(host(serial = 1)))
        val actions = mutableListOf<Action>()
        compose.setContent { PyComposeTheme { renderer(actions).Render(ir.value) } }
        compose.waitForIdle()

        compose.runOnIdle { ir.value = parse(host(serial = 1, message = "Changed")) }
        compose.waitForIdle()

        compose.onNodeWithText("Saved").assertExists()
        compose.onNodeWithText("Changed").assertDoesNotExist()
        assertTrue(actions.isEmpty())
        compose.onNodeWithText("Undo").performClick()
        compose.waitUntil(5000) { actions.isNotEmpty() }
        assertEquals(JsonPrimitive(1L), actions.single().payload["serial"])
    }

    @Test
    fun aFulfilledSerialDoesNotReplayAfterSavedStateRestoration() {
        val restoration = StateRestorationTester(compose)
        val ir = parse(host(serial = 1))
        val actions = mutableListOf<Action>()
        restoration.setContent { PyComposeTheme { renderer(actions).Render(ir) } }
        compose.waitForIdle()
        compose.onNodeWithText("Undo").performClick()
        compose.waitUntil(5000) { actions.isNotEmpty() }

        restoration.emulateSavedInstanceStateRestore()
        compose.waitForIdle()

        compose.onNodeWithText("Saved").assertDoesNotExist()
        assertEquals(1, actions.size)
    }

    @Test
    fun anUnfinishedRequestReattachesAfterSavedStateRestoration() {
        val restoration = StateRestorationTester(compose)
        val ir = parse(host(serial = 1))
        val actions = mutableListOf<Action>()
        restoration.setContent { PyComposeTheme { renderer(actions).Render(ir) } }
        compose.waitForIdle()

        restoration.emulateSavedInstanceStateRestore()
        compose.waitForIdle()

        compose.onNodeWithText("Saved").assertExists()
        assertTrue(actions.isEmpty())
        compose.onNodeWithText("Undo").performClick()
        compose.waitUntil(5000) { actions.isNotEmpty() }
        assertEquals(JsonPrimitive(1L), actions.single().payload["serial"])
    }

    @Test
    fun aNewSessionEpochAcceptsRestartedSerials() {
        val session = mutableStateOf(SessionSnapshot(parse(host(serial = 10)), 0))
        val actions = mutableListOf<Action>()
        compose.setContent {
            PyComposeTheme {
                key(session.value.epoch) { renderer(actions).Render(session.value.ir) }
            }
        }
        compose.waitForIdle()
        compose.onNodeWithText("Undo").performClick()
        compose.waitUntil(5000) { actions.size == 1 }

        compose.runOnIdle { session.value = SessionSnapshot(parse(host(serial = 1)), 1) }
        compose.waitForIdle()
        compose.onNodeWithText("Saved").assertExists()
        compose.onNodeWithText("Undo").performClick()
        compose.waitUntil(5000) { actions.size == 2 }

        assertEquals(
            listOf(JsonPrimitive(10L), JsonPrimitive(1L)),
            actions.map { it.payload["serial"] },
        )
    }

    private fun renderer(actions: MutableList<Action>): Renderer =
        Renderer(BuiltinComponents.registry(), ActionDispatcher { actions.add(it) })

    private fun parse(source: String): ValidatedIr = IrParser().parse(source).getOrThrow()

    private fun host(
        serial: Long,
        message: String = "Saved",
    ): String =
        """
        {"version":"0.1.0","schemaVersion":"1.23.0",
          "metadata":{"intents":{"demo.dismiss":{"payload":{
            "serial":{"required":true,"type":"integer"}}}}},
         "root":{"id":"root","type":"SnackbarHost","props":{
           "message":"$message","actionLabel":"Undo","serial":$serial,
           "onDismiss":{"fields":{},"intent":"demo.dismiss"}}}}
        """.trimIndent()
}
