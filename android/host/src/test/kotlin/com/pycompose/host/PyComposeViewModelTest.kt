package com.pycompose.host

import androidx.lifecycle.SavedStateHandle
import com.pycompose.ir.Lifecycle
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

    @Test fun `the configuration report lands before the first pull`() =
        runTest {
            val bridge = FakeBridge()
            val config =
                Lifecycle.payload(
                    orientation = "portrait",
                    darkMode = true,
                    locale = "en-US",
                    density = 2.75,
                )
            val model =
                PyComposeViewModel(
                    bridge,
                    SavedStateHandle(),
                    StandardTestDispatcher(testScheduler),
                    initialConfig = config,
                )
            advanceUntilIdle()

            // The first pull is the first frame the user sees, so the facts Python
            // cannot observe must land before it, not one snapshot later.
            assertEquals(listOf("start:home", "action:1", "pull"), bridge.calls)
            val envelope = bridge.sent.single()
            assertTrue(envelope.contains("\"onConfigChanged\""), envelope)
            assertTrue(envelope.contains("\"darkMode\":true"), envelope)
            assertNotNull(model.snapshot.value)
            model.close()
        }

    @Test fun `an initial configuration breaking the lifecycle contract fails at construction`() =
        runTest {
            val bridge = FakeBridge()
            val failure =
                runCatching {
                    PyComposeViewModel(
                        bridge,
                        SavedStateHandle(),
                        StandardTestDispatcher(testScheduler),
                        initialConfig = Lifecycle.route("home"),
                    )
                }
            assertTrue(failure.isFailure)
            assertEquals(emptyList<String>(), bridge.calls)
        }

    @Test fun `a burst of actions runs in order before one pull`() =
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
                    "action:2",
                    "pull",
                )
            assertEquals(expected, bridge.calls)
            assertSame(initial, model.snapshot.value)
            assertTrue(model.error.value.isNotEmpty())
            model.close()
        }

    @Test fun `a newer report replaces an older one to the same action still queued`() =
        runTest {
            val bridge = FakeBridge()
            val model =
                PyComposeViewModel(
                    bridge,
                    SavedStateHandle(),
                    StandardTestDispatcher(testScheduler),
                )
            advanceUntilIdle()
            model.dispatch(Action("increment", seq = 1))
            // A tap is not a report: it carries no settled value and always stands.
            model.dispatch(Action("increment"))
            model.dispatch(Action("increment", seq = 2))
            advanceUntilIdle()
            assertEquals(2, bridge.sent.size)
            assertTrue("seq" !in bridge.sent[0])
            assertTrue(bridge.sent[1].contains("\"seq\":2"))
            model.close()
        }

    @Test fun `an action names the snapshot that was on screen when the user acted`() =
        runTest {
            val bridge = FakeBridge().apply { serial = 7 }
            val model =
                PyComposeViewModel(
                    bridge,
                    SavedStateHandle(),
                    StandardTestDispatcher(testScheduler),
                )
            advanceUntilIdle()
            model.dispatch(Action("increment"))
            advanceUntilIdle()
            assertTrue(bridge.sent.single().contains("\"serial\":7"))
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
}
