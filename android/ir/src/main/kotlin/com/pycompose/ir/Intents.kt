package com.pycompose.ir

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import java.util.Base64

/**
 * Intents at the wire boundary.
 *
 * A control's action is an intent: the handler it calls and the fields it binds,
 * `{"fields": {...}, "intent": "..."}`, with each handler's payload contract stated
 * once in metadata under `intents`. Inside the host an intent travels as a handle, a
 * string that encodes the intent exactly, so reports, echoes and coalescing key on it
 * like any action id. A handle decodes back to its intent, so a tap on a screen that
 * is no longer current still sends exactly what the user saw.
 */
object Intents {
    private const val PREFIX = "app."
    private val encoder = Base64.getUrlEncoder().withoutPadding()
    private val decoder = Base64.getUrlDecoder()

    /** The handle for one intent object: its canonical text, encoded to a safe id. */
    fun handle(intent: JsonObject): String =
        PREFIX + encoder.encodeToString(intent.toString().toByteArray())

    /** The intent a handle stands for, or null for a registry action's plain name. */
    fun intent(handle: String): JsonObject? {
        if (!handle.startsWith(PREFIX)) return null
        val text = runCatching { String(decoder.decode(handle.removePrefix(PREFIX))) }.getOrNull()
        return text?.let { Json.parseToJsonElement(it) as? JsonObject }?.takeIf(::isIntent)
    }

    /** Whether a prop value is an intent rather than any other object. */
    fun isIntent(value: JsonElement?): Boolean =
        value is JsonObject && value.keys == setOf("fields", "intent")

    /** The envelope a tap sends Python for an action the host holds by handle. */
    fun envelope(
        actionId: String,
        payload: JsonObject,
        seq: Long?,
        serial: Long?,
        surface: String,
    ): String {
        val intent = intent(actionId)
        return buildJsonObject {
            put("fields", intent?.get("fields") ?: JsonObject(emptyMap()))
            put("intent", intent?.get("intent") ?: JsonPrimitive(actionId))
            put("payload", payload)
            seq?.let { put("seq", JsonPrimitive(it)) }
            serial?.let { put("serial", JsonPrimitive(it)) }
            put("surface", JsonPrimitive(surface))
        }.toString()
    }
}
