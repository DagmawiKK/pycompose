package com.pycompose.renderer

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/** Data-only envelope. Interpretation and validation belong to the Python worker. */
data class Action(
    val actionId: String,
    val payload: JsonObject = JsonObject(emptyMap()),
) {
    fun toJson(): String =
        buildJsonObject {
            put("actionId", actionId)
            put("payload", payload)
        }.toString()
}

class ActionDispatcher(
    private val enqueue: (Action) -> Unit,
) {
    fun dispatch(
        actionId: String,
        payload: JsonObject = JsonObject(emptyMap()),
    ) {
        enqueue(Action(actionId, payload))
    }
}
