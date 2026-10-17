package com.pycompose.host

import androidx.lifecycle.SavedStateHandle
import com.pycompose.host.bridge.BridgeSurface
import com.pycompose.ir.EffectRequest
import com.pycompose.ir.Effects
import com.pycompose.renderer.Action
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNotNull
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertSame
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

@OptIn(ExperimentalCoroutinesApi::class)
class PyComposeViewModelTest {
    @Test fun `reload changes the native session epoch even for identical IR`() =
        runTest {
            val bridge = FakeBridge()
            val saved = SavedStateHandle()
            val model = PyComposeViewModel(bridge, saved, StandardTestDispatcher(testScheduler))
            advanceUntilIdle()
            val first = checkNotNull(model.snapshot.value)

            model.navigate("details")
            advanceUntilIdle()
            assertEquals(first.epoch, checkNotNull(model.snapshot.value).epoch)

            model.reload()
            advanceUntilIdle()
            val reloaded = checkNotNull(model.snapshot.value)
            assertTrue(reloaded.epoch > first.epoch)
            assertEquals(first.ir.snapshot, reloaded.ir.snapshot)
            model.close()

            val rebuilt = PyComposeViewModel(bridge, saved, StandardTestDispatcher(testScheduler))
            advanceUntilIdle()
            assertTrue(checkNotNull(rebuilt.snapshot.value).epoch > reloaded.epoch)
            rebuilt.close()
        }

    @Test fun `a failed reload preserves the native session epoch`() =
        runTest {
            val bridge = FakeBridge()
            val model =
                PyComposeViewModel(
                    bridge,
                    SavedStateHandle(),
                    StandardTestDispatcher(testScheduler),
                )
            advanceUntilIdle()
            val first = model.snapshot.value
            bridge.reloadSucceeded = false

            model.reload()
            advanceUntilIdle()

            assertSame(first, model.snapshot.value)
            model.close()
        }

    @Test fun `actions are FIFO and rejected snapshots keep the previous IR`() =
        runTest {
            val bridge = FakeBridge()
            val model =
                PyComposeViewModel(
                    bridge,
                    SavedStateHandle(),
                    StandardTestDispatcher(testScheduler),
                )
            advanceUntilIdle()
            val initial = model.snapshot.value
            assertNotNull(initial)
            // Declared ids only: the host validates each envelope against the
            // binding or registry contract published by the current snapshot.
            model.dispatch(Action("increment"))
            model.dispatch(Action("increment"))
            advanceUntilIdle()
            val expected =
                listOf(
                    "start:home",
                    "pull",
                    "action:1",
                    "pull",
                    "action:2",
                    "pull",
                )
            assertEquals(expected, bridge.calls)
            assertSame(initial, model.snapshot.value)
            assertTrue(model.error.value.isNotEmpty())
            model.close()
        }

    @Test fun `an action outside the published contract never reaches the worker`() =
        runTest {
            val bridge = FakeBridge()
            val model =
                PyComposeViewModel(
                    bridge,
                    SavedStateHandle(),
                    StandardTestDispatcher(testScheduler),
                )
            advanceUntilIdle()
            assertNotNull(model.snapshot.value)
            model.dispatch(Action("undeclared"))
            advanceUntilIdle()
            assertEquals(listOf("start:home", "pull"), bridge.calls)
            assertTrue(model.error.value.isNotEmpty())
            model.close()
        }

    @Test fun `effects run once per snapshot and never again for an unchanged one`() =
        runTest {
            val bridge = FakeBridge()
            val ran = mutableListOf<String>()
            val model =
                PyComposeViewModel(
                    bridge,
                    SavedStateHandle(),
                    StandardTestDispatcher(testScheduler),
                )
            model.effectRunner = RecordingRunner(ran)
            advanceUntilIdle()
            assertEquals(listOf("toast:saved"), ran)

            // A second pull of the identical snapshot must not replay them.
            model.reload()
            advanceUntilIdle()
            assertEquals(listOf("toast:saved"), ran)

            bridge.pendingEffects = """[{"kind":"finish","payload":{}}]"""
            model.reload()
            advanceUntilIdle()
            assertEquals(listOf("toast:saved", "finish:"), ran)
            model.close()
        }

    @Test fun `an effect kind outside the published contract never reaches the host`() =
        runTest {
            val bridge = FakeBridge()
            val ran = mutableListOf<String>()
            val model =
                PyComposeViewModel(
                    bridge,
                    SavedStateHandle(),
                    StandardTestDispatcher(testScheduler),
                )
            model.effectRunner = RecordingRunner(ran)
            bridge.pendingEffects = """[{"kind":"notOnThisHost","payload":{}}]"""
            advanceUntilIdle()
            // The snapshot is unpublishable, so nothing renders and nothing runs.
            assertTrue(ran.isEmpty())
            assertNull(model.snapshot.value)
            assertTrue(model.error.value.isNotEmpty())
            model.close()
        }

    @Test fun `app data is saved and handed back when the process is rebuilt`() =
        runTest {
            val bridge = FakeBridge()
            bridge.pendingData = """{"tasks":[{"id":1,"title":"Kept","done":false}]}"""
            val saved = SavedStateHandle()
            val first = PyComposeViewModel(bridge, saved, StandardTestDispatcher(testScheduler))
            advanceUntilIdle()
            assertNotNull(first.snapshot.value)
            assertEquals(
                """{"tasks":[{"done":false,"id":1,"title":"Kept"}]}""",
                saved.get<String>("pycompose.data"),
            )
            first.close()

            // A new process reads the same handle; the restore bytes must flow.
            val second = PyComposeViewModel(bridge, saved, StandardTestDispatcher(testScheduler))
            advanceUntilIdle()
            assertTrue(
                bridge.starts
                    .last()
                    .restore
                    .isNotEmpty(),
            )
            assertTrue(
                bridge.starts
                    .last()
                    .restore
                    .contains("Kept"),
            )
            second.close()
        }

    @Test fun `an app that publishes no data saves nothing`() =
        runTest {
            val bridge = FakeBridge()
            bridge.pendingData = null
            val saved = SavedStateHandle()
            val model = PyComposeViewModel(bridge, saved, StandardTestDispatcher(testScheduler))
            advanceUntilIdle()
            assertNotNull(model.snapshot.value)
            assertNull(saved.get<String>("pycompose.data"))
            model.close()
        }

    @Test fun `oversized app state is refused with an explanation, not a crash`() =
        runTest {
            val bridge = FakeBridge()
            // Comfortably past what a Bundle can carry. Without a guard this
            // surfaces as a TransactionTooLargeException on save, naming nothing.
            bridge.pendingData = "{\"blob\":\"" + "x".repeat(200 * 1024) + "\"}"
            val saved = SavedStateHandle()
            val model = PyComposeViewModel(bridge, saved, StandardTestDispatcher(testScheduler))
            advanceUntilIdle()

            assertNull(saved.get<String>("pycompose.data"))
            assertTrue(model.error.value.contains("repository"), model.error.value)
            // The app keeps rendering; nothing crashed.
            assertNotNull(model.snapshot.value)
            model.close()
        }

    @Test fun `process recreation rebuilds with saved minimal route`() =
        runTest {
            val state = SavedStateHandle(mapOf("route" to "details"))
            val bridge = FakeBridge()
            val model = PyComposeViewModel(bridge, state, StandardTestDispatcher(testScheduler))
            advanceUntilIdle()
            assertEquals("start:details", bridge.calls.first())
            assertNotNull(model.snapshot.value)
            assertEquals("details", state.get<String>("route"))
            model.close()
        }

    @Test fun `navigating tells Python instead of rebuilding the session`() =
        runTest {
            val bridge = FakeBridge()
            val state = SavedStateHandle()
            val model = PyComposeViewModel(bridge, state, StandardTestDispatcher(testScheduler))
            advanceUntilIdle()
            val startsAfterBoot = bridge.calls.count { it.startsWith("start") }

            model.navigate("note:5")
            advanceUntilIdle()

            // Python is started exactly once, for the life of the ViewModel. A
            // navigation must not be able to discard the app's session, or no
            // ViewModel could ever be retained.
            assertEquals(startsAfterBoot, bridge.calls.count { it.startsWith("start") })
            assertTrue(bridge.sent.isNotEmpty())
            assertTrue(bridge.sent.last().contains("onRouteChanged"), bridge.sent.last())
            assertEquals("note:5", state.get<String>("route"))
            assertNotNull(model.snapshot.value)
            model.close()
        }

    @Test fun `a route change is delivered as a declared lifecycle action`() =
        runTest {
            val bridge = FakeBridge()
            val state = SavedStateHandle()
            val model = PyComposeViewModel(bridge, state, StandardTestDispatcher(testScheduler))
            advanceUntilIdle()

            model.navigate("note:9")
            advanceUntilIdle()

            val envelope = checkNotNull(bridge.sent.lastOrNull())
            assertTrue(envelope.contains("\"onRouteChanged\""), envelope)
            assertTrue(envelope.contains("\"route\":\"note:9\""), envelope)
            model.close()
        }

    @Test fun `a blank destination is refused before it can reach Python`() =
        runTest {
            val bridge = FakeBridge()
            val model =
                PyComposeViewModel(
                    bridge,
                    SavedStateHandle(),
                    StandardTestDispatcher(testScheduler),
                )
            advanceUntilIdle()
            assertTrue(runCatching { model.navigate("  ") }.isFailure)
            model.close()
        }

    @Test fun `effects requested while no runner is attached are not lost`() =
        runTest {
            val bridge = FakeBridge()
            val model =
                PyComposeViewModel(
                    bridge,
                    SavedStateHandle(),
                    StandardTestDispatcher(testScheduler),
                )
            // No runner yet: this is the window while an Activity is rotating.
            advanceUntilIdle()
            assertNotNull(model.snapshot.value)

            val ran = mutableListOf<String>()
            model.effectRunner = RecordingRunner(ran)

            // The snapshot the app produced while detached is delivered on attach.
            assertEquals(listOf("toast:saved"), ran)
            model.close()
        }

    @Test fun `a detached runner drains once and does not replay`() =
        runTest {
            val bridge = FakeBridge()
            val model =
                PyComposeViewModel(
                    bridge,
                    SavedStateHandle(),
                    StandardTestDispatcher(testScheduler),
                )
            advanceUntilIdle()

            val ran = mutableListOf<String>()
            model.effectRunner = RecordingRunner(ran)
            assertEquals(1, ran.size)

            // Re-attaching, as a new Activity does after rotation, must not
            // re-run effects the previous runner already performed.
            val again = mutableListOf<String>()
            model.effectRunner = RecordingRunner(again)
            assertEquals(emptyList<String>(), again)
            model.close()
        }

    private class RecordingRunner(
        private val ran: MutableList<String>,
        private val reported: MutableList<String> = mutableListOf(),
    ) : EffectRunner {
        override fun runAll(requests: List<EffectRequest>) {
            for (request in requests) {
                val known = setOf("navigate", "finish", "haptic", "openUrl", "toast")
                if (request.kind in known) {
                    ran.add("${request.kind}:${Effects.string(request, "message")}")
                } else {
                    reported.add("No host runner for effect ${request.kind}")
                }
            }
        }
    }

    private class FakeBridge : BridgeSurface {
        var reloadSucceeded = true
        val calls = mutableListOf<String>()
        val starts = mutableListOf<Start>()

        /** Every action envelope this bridge was asked to deliver to Python. */
        val sent = mutableListOf<String>()
        private var accepted = 0
        private var valid = true

        data class Start(
            val route: String,
            val restore: String,
        )

        /** Effects the worker attaches to every snapshot it hands back. */
        var pendingEffects = """[{"kind":"toast","payload":{"message":"saved"}}]"""

        /** App data the worker publishes, or null for an app that holds none. */
        var pendingData: String? = null

        override fun start(
            route: String,
            restore: String,
        ) {
            starts.add(Start(route, restore))
            calls.add("start:$route")
        }

        override fun acceptAction(action: String) {
            accepted++
            sent.add(action)
            calls.add("action:$accepted")
            // The worker goes silent after the first action, so the host must
            // keep rendering the last good snapshot.
            if (accepted > 1) valid = false
        }

        override fun fetchLatestSnapshot(): String {
            calls.add("pull")
            if (!valid) return "{}"
            val golden = checkNotNull(javaClass.getResource("/ir_counter.json")).readText()
            val data = pendingData
            val metadata =
                if (data == null) {
                    """{"effects":$pendingEffects}"""
                } else {
                    """{"effects":$pendingEffects,"data":$data}"""
                }
            return golden
                .replace("\"schemaVersion\":\"1.0.0\"", "\"schemaVersion\":\"1.4.0\"")
                .replace("{\"root\"", "{\"metadata\":$metadata,\"root\"")
        }

        override fun fetchLatestError(): String = ""

        override fun reload(
            route: String,
            restore: String,
        ): Boolean {
            calls.add("reload:$route")
            return reloadSucceeded
        }
    }
}
