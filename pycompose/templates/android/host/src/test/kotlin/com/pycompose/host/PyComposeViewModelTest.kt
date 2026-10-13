package com.pycompose.host

import androidx.lifecycle.SavedStateHandle
import com.pycompose.host.bridge.BridgeSurface
import com.pycompose.renderer.Action
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNotNull
import org.junit.jupiter.api.Assertions.assertSame
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

@OptIn(ExperimentalCoroutinesApi::class)
class PyComposeViewModelTest {
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
            model.dispatch(Action("first"))
            model.dispatch(Action("broken"))
            advanceUntilIdle()
            val expected =
                listOf(
                    "start:home",
                    "pull",
                    "action:first",
                    "pull",
                    "action:broken",
                    "pull",
                )
            assertEquals(expected, bridge.calls)
            assertSame(initial, model.snapshot.value)
            assertTrue(model.error.value.isNotEmpty())
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

    private class FakeBridge : BridgeSurface {
        val calls = mutableListOf<String>()
        private var valid = true

        override fun start(route: String) {
            calls.add("start:$route")
        }

        override fun acceptAction(action: String) {
            calls.add("action:" + if (action.contains("broken")) "broken" else "first")
            valid = !action.contains("broken")
        }

        override fun fetchLatestSnapshot(): String {
            calls.add("pull")
            val golden = checkNotNull(javaClass.getResource("/ir_counter.json")).readText()
            return if (valid) golden else "{}"
        }

        override fun fetchLatestError(): String = ""

        override fun reload(route: String) = Unit
    }
}
