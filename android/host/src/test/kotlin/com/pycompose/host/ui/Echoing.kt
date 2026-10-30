package com.pycompose.host.ui

import com.pycompose.ir.Intents
import com.pycompose.renderer.Action
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject

/**
 * [source] as the bridge publishes it once the app has answered [actions]: its metadata
 * echoes each action's latest report number, so a holder treats the snapshot's desired
 * value as an answer to its latest report rather than a stale one.
 */
internal fun echoing(
    source: String,
    actions: List<Action>,
): String {
    val echoes = actions.mapNotNull { action -> action.seq?.let { action.actionId to it } }.toMap()
    if (echoes.isEmpty()) return source
    val root = Json.parseToJsonElement(source).jsonObject
    val metadata = root["metadata"]?.jsonObject ?: JsonObject(emptyMap())
    val echoed =
        JsonArray(
            echoes.map { (id, seq) ->
                val target = Intents.intent(id) ?: JsonPrimitive(id)
                JsonObject(mapOf("seq" to JsonPrimitive(seq), "target" to target))
            },
        )
    return JsonObject(root + ("metadata" to JsonObject(metadata + ("echoes" to echoed)))).toString()
}
