package com.pycompose.host

import android.util.Log
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.withFrameNanos
import androidx.tracing.Trace
import java.util.concurrent.atomic.AtomicInteger

/**
 * One trace span per host command, from the moment it is queued to the first frame that
 * shows its result, so a device trace attributes an action's time to the queue, the Python
 * pass, the pull, the host apply and the frame. Every call is a no-op unless a trace is
 * being recorded.
 */
internal object ActionTrace {
    private const val SPAN = "pycompose.action"
    private val cookies = AtomicInteger()

    /** Open a command's span when it is queued; the returned cookie closes it. */
    fun begin(): Int = cookies.incrementAndGet().also { Trace.beginAsyncSection(SPAN, it) }

    /** Close a command's span: its frame was drawn, or it changed nothing to draw. */
    fun end(cookie: Int) = Trace.endAsyncSection(SPAN, cookie)

    /** Run one stage of a command inside its own trace section. */
    inline fun <T> stage(
        label: String,
        block: () -> T,
    ): T {
        Trace.beginSection(label)
        try {
            return block()
        } finally {
            Trace.endSection()
        }
    }

    /** Close [session]'s span on the next frame, which shows it or a newer snapshot. */
    @Composable
    fun EndOnFrame(session: SessionSnapshot) {
        LaunchedEffect(session) {
            try {
                withFrameNanos { }
                session.timing?.let { Log.i(PassTiming.TAG, it.line(System.nanoTime())) }
            } finally {
                session.traces.forEach(::end)
            }
        }
    }
}
