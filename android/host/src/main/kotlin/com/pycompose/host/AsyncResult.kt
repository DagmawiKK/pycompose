package com.pycompose.host

import android.os.Handler
import android.os.Looper
import com.pycompose.renderer.Action
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import java.util.concurrent.atomic.AtomicReference

/**
 * The one door a background Python thread knocks on.
 *
 * Python cannot call back into the ViewModel directly: it holds no reference to
 * one, and inventing a registry of live views would put a lifecycle problem in
 * the middle of a threading one. Instead the host keeps a single process-wide
 * sink, and this is where a finished background result enters the host.
 *
 * The call may arrive on any thread. Nothing here touches app state or Python;
 * the result is marshalled to the main thread and queued, so the worker picks it
 * up through exactly the same path as a tap.
 */
object AsyncResult {
    private val sink = AtomicReference<((String, String) -> Unit)?>(null)
    private val admission = AtomicReference<((String, String) -> Boolean)?>(null)
    private val main = AtomicReference<Handler?>()

    /**
     * Point results at [deliver]; pass null when the owning view goes away.
     *
     * The listener runs on the main thread, so it must not throw: an exception
     * here would take the process down with it. Reporting a malformed result is
     * the listener's job, not this object's -- swallowing the failure here
     * instead would leave no sign that a result was lost.
     */
    fun listen(deliver: ((String, String) -> Unit)?): AutoCloseable {
        sink.set(deliver)
        return AutoCloseable { sink.compareAndSet(deliver, null) }
    }

    /** Register only thread-safe queue admission, never UI or Python execution. */
    fun listenAdmission(accept: ((String, String) -> Boolean)?): AutoCloseable {
        admission.set(accept)
        return AutoCloseable { admission.compareAndSet(accept, null) }
    }

    /** Acknowledged variant for registered outcomes. No unbounded Handler backlog. */
    @JvmStatic
    fun offer(
        actionId: String,
        payload: String,
    ): Boolean = admission.get()?.invoke(actionId, payload) ?: false

    /**
     * Called from Python on whatever thread the work finished on.
     *
     * Called reflectively by Chaquopy, so the signature is deliberately two
     * strings: an action id and its canonical payload text.
     */
    @JvmStatic
    fun deliver(
        actionId: String,
        payload: String,
    ) {
        val deliver = sink.get() ?: return
        // Built on first use rather than at class load: an app that never does
        // background work should not pay for a main-thread Handler, and should
        // not need a Looper just to start.
        val handler = main.get() ?: Handler(Looper.getMainLooper()).also { main.set(it) }
        handler.post { deliver(actionId, payload) }
    }
}

/** Producer-side data validation and acknowledged thread-safe admission only. */
internal class OutcomeAdmission(
    private val accept: (Action) -> Boolean,
    private val rejected: () -> Unit,
) {
    fun offer(
        actionId: String,
        payload: String,
    ): Boolean =
        runCatching {
            val element = Json.parseToJsonElement(payload)
            require(element is JsonObject) { "Async result must be an object" }
            accept(Action(actionId, element))
        }.getOrElse {
            rejected()
            false
        }
}
