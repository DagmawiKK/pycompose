package com.pycompose.ir

import com.pycompose.ir.generated.IRRoot
import com.pycompose.ir.generated.IrContract
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject

/** Only the parser can construct this proof that a snapshot passed the wire gate. */
class ValidatedIr internal constructor(
    val snapshot: IRRoot,
)

/** Fail-closed parser; failures are values, not exceptions crossing the host boundary. */
class IrParser(
    private val minSchemaVersion: String = IrContract.MIN_SCHEMA_VERSION,
) {
    companion object {
        /** Syntax/type gate for standalone modifier consumers; callers supply known actions. */
        fun validateModifier(
            value: JsonObject,
            actionIds: Set<String>,
        ): Result<Unit> = runCatching { WireValidator.modifier(value, "modifier", actionIds) }
    }

    private val json =
        Json {
            ignoreUnknownKeys = false
            isLenient = false
            coerceInputValues = false
            allowSpecialFloatingPointValues = false
            classDiscriminator = "type"
        }

    private val validated = ValidationCache()
    private val audited = IdentityMemo<Unit>()
    private val lowered = IdentityMemo<IntentLowering.Lowered>()
    private val decoder = NodeDecoder(json)

    /** Decode one full snapshot and reject unsupported versions before rendering. */
    fun parse(source: String): Result<ValidatedIr> =
        runCatching { read(source) }.mapCatching(::accept)

    /** One JSON object with no duplicate keys anywhere in it. */
    internal fun read(source: String): JsonObject {
        JsonAudit.uniqueKeys(source, json)
        return json.parseToJsonElement(source) as? JsonObject ?: error("Snapshot must be an object")
    }

    /**
     * Validate and decode a snapshot already parsed to JSON.
     *
     * Subtrees that are the same objects as last time -- what a patched snapshot
     * shares with its base -- are neither validated nor decoded again. A failure
     * forgets everything, since a failed pass may have recorded subtrees whose
     * descendants were never checked.
     */
    internal fun accept(raw: JsonObject): ValidatedIr =
        runCatching {
            validated(
                IntentLowering.lower(raw, lowered),
            )
        }.onFailure { forget() }.getOrThrow()

    private fun validated(raw: JsonObject): ValidatedIr {
        VersionGate.check(
            WireValidator.string(raw["schemaVersion"], "schemaVersion"),
            WireValidator.string(raw["version"], "version"),
            minSchemaVersion,
        )
        WireValidator.validate(raw, validated)
        audited.start()
        JsonAudit.scalars(raw, audited)
        return ValidatedIr(
            IRRoot(
                version = WireValidator.string(raw["version"], "version"),
                schemaVersion = WireValidator.string(raw["schemaVersion"], "schemaVersion"),
                root = decoder.decode(raw["root"] as JsonObject),
                metadata = raw["metadata"] as? JsonObject,
            ),
        )
    }

    private fun forget() {
        validated.reset()
        audited.reset()
        lowered.reset()
        decoder.reset()
    }
}
