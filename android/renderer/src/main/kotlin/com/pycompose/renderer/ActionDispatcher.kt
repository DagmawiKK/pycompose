package com.pycompose.renderer

import com.pycompose.ir.SnapshotStream
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * Data-only envelope. Interpretation and validation belong to the Python worker.
 *
 * @param seq The report sequence number of a settled value a holder reported, which the
 *   app's next snapshot echoes; null for actions that report nothing.
 * @param serial The snapshot the user acted on, so the app resolves the action against what
 *   was on screen; null resolves it against the latest snapshot.
 * @param surface The surface the action came from; every action names one.
 */
data class Action(
    val actionId: String,
    val payload: JsonObject = JsonObject(emptyMap()),
    val seq: Long? = null,
    val serial: Long? = null,
    val surface: String = SnapshotStream.MAIN_SURFACE,
) {
    fun toJson(): String =
        buildJsonObject {
            put("actionId", actionId)
            put("payload", payload)
            seq?.let { put("seq", it) }
            serial?.let { put("serial", it) }
            put("surface", surface)
        }.toString()
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
