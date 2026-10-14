package com.pycompose.host

import android.os.Handler
import android.os.Looper
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
    private val main = AtomicReference<Handler?>()

    /**
     * Point results at [deliver]; pass null when the owning view goes away.
     *
     * The listener runs on the main thread, so it must not throw: an exception
     * here would take the process down with it. Reporting a malformed result is
     * the listener's job, not this object's -- swallowing the failure here
     * instead would leave no sign that a result was lost.
     */
    fun listen(deliver: ((String, String) -> Unit)?) {
        sink.set(deliver)
    }

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
