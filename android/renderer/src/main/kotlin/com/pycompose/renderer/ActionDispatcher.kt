package com.pycompose.renderer

import com.pycompose.ir.Intents
import com.pycompose.ir.SnapshotStream
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * Data-only envelope. Interpretation and validation belong to the Python worker.
 *
 * @param seq The report sequence number of a settled value a holder reported, which the
 *   app's next snapshot echoes; null for actions that report nothing.
 * @param serial The snapshot the user acted on, so the app resolves the action against what
 *   was on screen; null resolves it against the latest snapshot.
 * @param surface The surface the action came from; every action names one.
 * @param trace The host's trace id for the command carrying it, so a failure the app
 *   reports names the input behind it; null when untraced.
 */
data class Action(
    val actionId: String,
    val payload: JsonObject = JsonObject(emptyMap()),
    val seq: Long? = null,
    val serial: Long? = null,
    val surface: String = SnapshotStream.MAIN_SURFACE,
    val trace: String? = null,
) {
    fun toJson(): String {
        val envelope = Intents.envelope(actionId, payload, seq, serial, surface)
        return (trace?.let { JsonObject(envelope + ("trace" to JsonPrimitive(it))) } ?: envelope)
            .toString()
    }
}

class ActionDispatcher(
    private val enqueue: (Action) -> Unit,
) {
    fun dispatch(
        actionId: String,
        payload: JsonObject = JsonObject(emptyMap()),
        seq: Long? = null,
    ) {
        enqueue(Action(actionId, payload, seq))
    }
}
