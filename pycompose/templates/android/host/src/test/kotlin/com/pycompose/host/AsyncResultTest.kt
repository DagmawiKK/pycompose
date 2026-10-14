package com.pycompose.host

import android.os.Looper
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

/**
 * The door background Python results come through.
 *
 * The contract under test: a result may arrive on any thread, is moved to the main
 * thread before anyone sees it, and is dropped rather than delivered once the
 * owning view has gone -- a closed view has no worker left to re-render into.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class AsyncResultTest {
    @Test
    fun `a result is delivered with its action id and payload untouched`() {
        val seen = mutableListOf<Pair<String, String>>()
        AsyncResult.listen { actionId, payload -> seen.add(actionId to payload) }
        try {
            AsyncResult.deliver("notes.arrived", """{"value":"fetched"}""")
            shadowOf(Looper.getMainLooper()).idle()

            assertEquals(listOf("notes.arrived" to """{"value":"fetched"}"""), seen)
        } finally {
            AsyncResult.listen(null)
        }
    }

    @Test
    fun `a result is handed over on the main thread, not the caller's`() {
        val onMain = AtomicBoolean(false)
        AsyncResult.listen { _, _ ->
            onMain.set(Looper.getMainLooper().thread == Thread.currentThread())
        }
        try {
            val producer = Executors.newSingleThreadExecutor()
            producer
                .submit { AsyncResult.deliver("notes.arrived", """{"value":"x"}""") }
                .get(5, TimeUnit.SECONDS)
            shadowOf(Looper.getMainLooper()).idle()

            assertTrue(onMain.get())
            producer.shutdownNow()
        } finally {
            AsyncResult.listen(null)
        }
    }

    @Test
    fun `a result arriving after the view closes is dropped`() {
        val seen = mutableListOf<String>()
        AsyncResult.listen { actionId, _ -> seen.add(actionId) }
        AsyncResult.listen(null)

        AsyncResult.deliver("notes.arrived", """{"value":"too late"}""")
        shadowOf(Looper.getMainLooper()).idle()

        assertEquals(emptyList<String>(), seen)
    }

    @Test
    fun `a busy pool is never held up by delivery`() {
        AsyncResult.listen { _, _ -> Unit }
        try {
            val pool = Executors.newFixedThreadPool(4)
            val gate = CountDownLatch(1)
            val finished = CountDownLatch(8)

            repeat(8) {
                pool.submit {
                    gate.await()
                    AsyncResult.deliver("notes.arrived", """{"value":"x"}""")
                    finished.countDown()
                }
            }
            gate.countDown()

            // Delivery is asynchronous by design. A producer must finish even
            // while the main looper is still busy, or the pool becomes the new
            // bottleneck it was introduced to avoid.
            assertTrue(finished.await(5, TimeUnit.SECONDS))
            pool.shutdownNow()
        } finally {
            AsyncResult.listen(null)
        }
    }
}
