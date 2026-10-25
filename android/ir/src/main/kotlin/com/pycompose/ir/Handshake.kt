package com.pycompose.ir

import com.pycompose.ir.generated.IrContract
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonArray

/**
 * The session handshake: what each side of the bridge speaks.
 *
 * The host and the Python app may come from different builds, so before a session starts
 * each states its protocol version and the capabilities it offers, and each checks the
 * other offers what it requires. A mismatch fails at startup naming what is missing,
 * instead of misrendering later. New wire shapes arrive as capabilities, so each grows
 * without a flag day.
 */
object Handshake {
    /** Bumped only by a change no capability can describe. */
    const val PROTOCOL = 1

    /** What this host offers the app. */
    val CAPABILITIES: Set<String> = emptySet()

    /** What this host needs the app to offer. */
    val REQUIRED: Set<String> = emptySet()

    /**
     * This host's handshake, sent before the session starts.
     *
     * It lists the component types this host renders, so the app replaces one it
     * lacks with its declared fallback before sending it (ADR-0050).
     */
    fun offer(): String =
        buildJsonObject {
            put("protocol", PROTOCOL)
            putJsonArray(
                "capabilities",
            ) { CAPABILITIES.sorted().forEach { add(JsonPrimitive(it)) } }
            putJsonArray("components") {
                IrContract.components.keys
                    .sorted()
                    .forEach { add(JsonPrimitive(it)) }
            }
        }.toString()

    /** Check the app's answer; throws naming the protocol or capabilities that do not match. */
    fun accept(
        answer: String,
        required: Set<String> = REQUIRED,
    ) {
        val app = Json.parseToJsonElement(answer) as? JsonObject ?: error("Malformed app handshake")
        val protocol =
            (app["protocol"] as? JsonPrimitive)?.intOrNull ?: error("Malformed app handshake")
        val offered =
            (app["capabilities"] as? JsonArray ?: error("Malformed app handshake"))
                .map { WireValidator.string(it, "capabilities") }
                .toSet()
        check(protocol == PROTOCOL) { "Bridge protocol mismatch: host $PROTOCOL, app $protocol" }
        val missing = required - offered
        check(missing.isEmpty()) { "App lacks capabilities: ${missing.sorted().joinToString()}" }
    }
}
