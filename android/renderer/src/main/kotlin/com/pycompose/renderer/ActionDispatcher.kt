package com.pycompose.renderer

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * Data-only envelope. Interpretation and validation belong to the Python worker.
 *
 * @param seq The report sequence number of a settled value a holder reported, which the
 *   app's next snapshot echoes; null for actions that report nothing.
 */
data class Action(
    val actionId: String,
    val payload: JsonObject = JsonObject(emptyMap()),
    val seq: Long? = null,
) {
    fun toJson(): String =
        buildJsonObject {
            put("actionId", actionId)
            put("payload", payload)
            seq?.let { put("seq", it) }
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
