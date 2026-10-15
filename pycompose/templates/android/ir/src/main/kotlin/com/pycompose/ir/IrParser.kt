package com.pycompose.ir

import com.pycompose.ir.generated.IRRoot
import com.pycompose.ir.generated.IrContract
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.decodeFromJsonElement

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

    /** Decode one full snapshot and reject unsupported versions before rendering. */
    fun parse(source: String): Result<ValidatedIr> =
        runCatching {
            JsonAudit.uniqueKeys(source, json)
            val raw =
                json.parseToJsonElement(source) as? JsonObject
                    ?: error("Snapshot must be an object")
            VersionGate.check(
                WireValidator.string(raw["schemaVersion"], "schemaVersion"),
                WireValidator.string(raw["version"], "version"),
                minSchemaVersion,
            )
            WireValidator.validate(raw)
            JsonAudit.scalars(raw)
            val snapshot = json.decodeFromJsonElement<IRRoot>(raw)
            ValidatedIr(snapshot)
        }
}
