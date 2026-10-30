package com.pycompose.ir

import com.pycompose.ir.generated.IrContract
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject

/** One validated request for the host to execute exactly once, in order. */
data class EffectRequest(
    val kind: String,
    val payload: JsonObject,
)

/**
 * Reads effect requests from snapshot metadata. Effects are data only: the host
 * owns the behaviour behind every kind and never calls back into Python.
 */
object Effects {
    private val kindSyntax = Regex("[A-Za-z][A-Za-z0-9]*")
    private const val SCHEMA = "1.4.0"

    fun read(
        metadata: JsonObject?,
        schema: String,
    ): List<EffectRequest> {
        val raw = metadata?.get("effects") ?: return emptyList()
        require(VersionGate.available(schema, SCHEMA)) { "Effects require schema $SCHEMA" }
        val array = raw as? JsonArray ?: error("effects must be an array")
        return array.map { item ->
            val effect = item as? JsonObject ?: error("Effect must be an object")
            require(effect.keys == setOf("kind", "payload")) { "Invalid effect fields" }
            val kind = WireValidator.string(effect["kind"], "effect.kind")
            require(kindSyntax.matches(kind)) { "Invalid effect kind: $kind" }
            val rules =
                checkNotNull(IrContract.effectPayloads[kind]) { "Undeclared effect kind: $kind" }
            val payload =
                effect["payload"] as? JsonObject ?: error("Effect payload must be an object")
            WireValidator.properties(payload, rules, "effect.$kind.payload")
            EffectRequest(kind, payload)
        }
    }
}
