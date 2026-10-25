package com.pycompose.host

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject

/**
 * One pass's time by stage, in milliseconds, logged as one line when the frame
 * showing it is drawn: what `pycompose bench` reads. Debug builds only.
 *
 * @param queue From the oldest command's arrival to the pass starting on the worker.
 * @param python Running the commands: the host's action check, then the Python pass.
 * @param pull Fetching the snapshot, which Python diffs against the host's.
 * @param apply Parsing and validating it on the host.
 * @param phases Python's own split of [python], as JSON milliseconds by phase.
 * @param commands Commands the pass ran, after coalescing.
 * @param appliedAt `System.nanoTime()` when the snapshot was applied.
 */
data class PassTiming(
    val queue: Double,
    val python: Double,
    val pull: Double,
    val apply: Double,
    val phases: String,
    val commands: Int,
    val appliedAt: Long,
) {
    /** The log line, with the frame's share measured up to [drawnAt]. */
    fun line(drawnAt: Long): String {
        val frame = millis(drawnAt - appliedAt)
        val stages =
            mapOf(
                "queue" to queue,
                "python" to python,
                "pull" to pull,
                "apply" to apply,
                "frame" to frame,
                "total" to queue + python + pull + apply + frame,
            ).mapValues { JsonPrimitive(it.value) }
        val split = runCatching { Json.parseToJsonElement(phases).jsonObject }.getOrNull()
        return JsonObject(
            stages + (split ?: emptyMap()) + ("commands" to JsonPrimitive(commands)),
        ).toString()
    }

    companion object {
        /** The logcat tag each pass's line is written under. */
        const val TAG = "PyCompose.pass"

        /** Nanoseconds as milliseconds, to a hundredth. */
        fun millis(nanos: Long): Double = Math.round(nanos / NANOS_PER_HUNDREDTH) / HUNDREDTHS

        private const val NANOS_PER_HUNDREDTH = 10_000.0
        private const val HUNDREDTHS = 100.0
    }
}
