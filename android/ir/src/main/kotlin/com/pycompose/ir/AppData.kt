package com.pycompose.ir

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * Reads the app's own data out of snapshot metadata. The host stores these bytes
 * and hands them straight back after process death, so it never interprets them:
 * the app owns the shape, the host only carries the value.
 */
object AppData {
    private const val SCHEMA = "1.4.0"

    /**
     * Canonical text of the published data, or an empty string when the app holds
     * none. Keys are sorted so equal data always yields equal text, which is what
     * lets the host skip rewriting saved state that has not meaningfully changed.
     * Throws when the member is present but unusable, which a snapshot that
     * passed validation should never do.
     */
    fun read(
        metadata: JsonObject?,
        schema: String,
    ): String {
        val raw = metadata?.get("data") ?: return ""
        require(VersionGate.available(schema, SCHEMA)) { "App data requires schema $SCHEMA" }
        require(raw is JsonObject) { "App data must be an object" }
        return canonical(raw)
    }

    private fun canonical(value: JsonElement): String =
        when (value) {
            is JsonObject ->
                value.entries
                    .sortedBy { it.key }
                    .joinToString(separator = ",", prefix = "{", postfix = "}") { (key, member) ->
                        "${canonical(JsonPrimitive(key))}:${canonical(member)}"
                    }
            is JsonArray ->
                value.joinToString(separator = ",", prefix = "[", postfix = "]") { canonical(it) }
            else -> value.toString()
        }
}
