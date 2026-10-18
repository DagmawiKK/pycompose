package com.pycompose.host

import androidx.lifecycle.SavedStateHandle
import com.pycompose.host.bridge.BridgeSurface
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

@OptIn(ExperimentalCoroutinesApi::class)
class OutcomeAdmissionTest {
    @Test fun `obsolete teardown preserves replacement`() =
        runTest {
            val old =
                PyComposeViewModel(
                    RecordingBridge(),
                    SavedStateHandle(),
                    StandardTestDispatcher(testScheduler),
                )
            val replacement =
                PyComposeViewModel(
                    RecordingBridge(),
                    SavedStateHandle(),
                    StandardTestDispatcher(testScheduler),
                )
            old.close()
            assertTrue(AsyncResult.offer("pycompose.task.replacement", "{}"))
            old.close()
            assertTrue(AsyncResult.offer("pycompose.task.still-active", "{}"))
            advanceUntilIdle()
            replacement.close()
            assertEquals(false, AsyncResult.offer("pycompose.task.closed", "{}"))
            advanceUntilIdle()
        }

    @Test fun `full queues reject outcomes and allow retry`() =
        runTest {
            val model =
                PyComposeViewModel(
                    RecordingBridge(),
                    SavedStateHandle(),
                    StandardTestDispatcher(testScheduler),
                )
            repeat(64) { index ->
                assertTrue(AsyncResult.offer("pycompose.task.$index", "{}"))
            }
            assertEquals(false, AsyncResult.offer("pycompose.task.overflow", "{}"))
            advanceUntilIdle()
            assertTrue(AsyncResult.offer("pycompose.task.retry", "{}"))
            model.close()
            assertEquals(false, AsyncResult.offer("pycompose.task.closed", "{}"))
            advanceUntilIdle()
        }

    @Test fun `worker teardown runs only once`() =
        runTest {
            val bridge = RecordingBridge()
            val model =
                PyComposeViewModel(
                    bridge,
                    SavedStateHandle(),
                    StandardTestDispatcher(testScheduler),
                )
            advanceUntilIdle()
            model.close()
            model.close()
            assertEquals(0, bridge.closes)
            advanceUntilIdle()
            assertEquals(1, bridge.closes)
        }

    private class RecordingBridge : BridgeSurface {
        var closes = 0

        override fun start(
            route: String,
            restore: String,
        ) = Unit

        override fun acceptAction(action: String) = Unit

        override fun fetchLatestSnapshot(): String =
            """
            {"schemaVersion":"1.23.0","version":"0.1.0",
             "root":{"id":"text","type":"Text","props":{"text":"ready"}}}
            """.trimIndent()

        override fun fetchLatestError(): String = ""

        override fun reload(
            route: String,
            restore: String,
        ): Boolean = false

        override fun close() {
            closes++
        }
    }
}
