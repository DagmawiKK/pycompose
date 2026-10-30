package com.pycompose.host

import androidx.lifecycle.SavedStateHandle
import com.pycompose.ir.EffectRequest
import com.pycompose.ir.generated.Effect
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNotNull
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

/** Effects run once per snapshot, survive a detached runner and never replay. */
@OptIn(ExperimentalCoroutinesApi::class)
class PyComposeViewModelEffectsTest {
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
                    val message = (Effect.of(request) as? Effect.Toast)?.message.orEmpty()
                    ran.add("${request.kind}:$message")
                } else {
                    reported.add("No host runner for effect ${request.kind}")
                }
            }
        }
    }
}
