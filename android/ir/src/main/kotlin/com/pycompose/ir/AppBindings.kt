package com.pycompose.ir

import com.pycompose.ir.generated.IrContract
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.longOrNull

/** Pure binding data. Kotlin never resolves or holds a Python handler. */
data class AppBinding(
    val payload: Map<String, PropertyRule>,
    val bound: JsonObject,
) {
    val eventFields: Map<String, PropertyRule> get() = payload.filterKeys { it !in bound }
}

object AppBindings {
    private val idSyntax = Regex("app\\.[A-Za-z0-9_.-]+")
    private val fieldSyntax = Regex("[a-z][A-Za-z0-9]*")
    private val payloadTypes = setOf("string", "integer", "number", "boolean", "enum")

    fun read(
        metadata: JsonObject?,
        schema: String,
    ): Map<String, AppBinding> {
        val raw = metadata?.get("actionBindings") ?: return emptyMap()
        require(VersionGate.available(schema, "1.2.0")) { "App bindings require schema 1.2.0" }
        val bindings = raw as? JsonObject ?: error("actionBindings must be an object")
        return bindings.mapValues { (id, value) ->
            require(idSyntax.matches(id)) { "Invalid app binding id" }
            val spec = value as? JsonObject ?: error("Binding must be an object")
            require(
                spec.keys == setOf("handlerId", "payload", "bound"),
            ) { "Invalid binding fields" }
            require(WireValidator.string(spec["handlerId"], "handlerId").isNotEmpty())
            val payload = spec["payload"] as? JsonObject ?: error("Missing payload schema")
            val rules =
                payload.mapValues { (name, definition) ->
                    require(fieldSyntax.matches(name)) { "Invalid payload field name" }
                    rule(definition as? JsonObject ?: error("Invalid payload field"))
                }
            val bound = spec["bound"] as? JsonObject ?: error("Missing bound payload")
            WireValidator.properties(bound, rules, "bound", requireFields = false)
            AppBinding(rules, bound)
        }
    }

    private fun rule(definition: JsonObject): PropertyRule {
        require(definition.keys.all { it in setOf("type", "required", "values", "nullable") })
        val type = WireValidator.string(definition["type"], "payload.type")
        require(type in payloadTypes) { "Unsupported payload type" }
        val required =
            definition["required"]?.let {
                require(!it.jsonPrimitive.isString)
                checkNotNull(it.jsonPrimitive.booleanOrNull)
            } ?: false
        val values =
            definition["values"]
                ?.let { raw ->
                    (raw as? JsonArray ?: error("values must be an array"))
                        .map { WireValidator.string(it, "payload.values") }
                        .toSet()
                }.orEmpty()
        require(type != "enum" || values.isNotEmpty()) { "Empty payload enum" }
        // A report that may carry null: a derived family's cleared property.
        val nullable =
            definition["nullable"]?.let {
                require(!it.jsonPrimitive.isString)
                checkNotNull(it.jsonPrimitive.booleanOrNull)
            } ?: false
        return PropertyRule(type, required, values, nullable = nullable)
    }

    /**
     * Host-created event data must satisfy the handler's contract.
     *
     * The tap names its intent, which carries its own bound fields, so it is checked
     * against its handler's contract even when the snapshot it came from is gone.
     */
    fun validateAction(
        source: String,
        ir: ValidatedIr,
    ): Result<Unit> =
        runCatching {
            val raw =
                Json.parseToJsonElement(source) as? JsonObject ?: error("Invalid action envelope")
            require(
                raw.keys.all {
                    it in
                        setOf("fields", "intent", "payload", "seq", "serial", "surface", "trace")
                },
            ) { "Invalid action envelope" }
            raw["surface"]?.let { WireValidator.string(it, "surface") }
            for (counter in listOf("seq", "serial")) {
                raw[counter]?.let { value ->
                    require(
                        value is JsonPrimitive && !value.isString && (value.longOrNull ?: 0) > 0,
                    ) {
                        "$counter must be a positive integer"
                    }
                }
            }
            val name = WireValidator.string(raw["intent"], "intent")
            val fields = raw["fields"] as? JsonObject ?: JsonObject(emptyMap())
            val payload = raw["payload"] as? JsonObject ?: error("Invalid action payload")
            val bindings = read(ir.snapshot.metadata, ir.snapshot.schemaVersion)
            if (name in IrContract.actionPayloads) {
                require(fields.isEmpty()) { "Registry actions bind no fields" }
                validatePayload(name, payload, bindings).getOrThrow()
            } else {
                val handle =
                    Intents.handle(
                        JsonObject(
                            mapOf(
                                "fields" to fields,
                                "intent" to JsonPrimitive(name),
                            ),
                        ),
                    )
                val binding = bindings[handle] ?: contract(name, fields, ir)
                validatePayload(handle, payload, mapOf(handle to binding)).getOrThrow()
            }
            JsonAudit.scalars(raw)
        }

    /** The binding a stale tap's intent means under its handler's current contract. */
    private fun contract(
        name: String,
        fields: JsonObject,
        ir: ValidatedIr,
    ): AppBinding {
        val contracts = ir.snapshot.metadata?.get("intents") as? JsonObject
        val stated = contracts?.get(name) as? JsonObject ?: error("Unknown intent: $name")
        val payload = stated["payload"] as? JsonObject ?: error("Missing payload schema")
        val rules =
            payload.mapValues { (field, definition) ->
                require(fieldSyntax.matches(field)) { "Invalid payload field name" }
                rule(definition as? JsonObject ?: error("Invalid payload field"))
            }
        WireValidator.properties(fields, rules, "fields", requireFields = false)
        return AppBinding(rules, fields)
    }

    /** Check a host-produced payload using the same contract as an inbound action. */
    fun validatePayload(
        id: String,
        payload: JsonObject,
        bindings: Map<String, AppBinding>,
    ): Result<Unit> =
        runCatching {
            val fields =
                bindings[id]?.eventFields ?: checkNotNull(IrContract.actionPayloads[id]) {
                    "Unknown active action binding: $id"
                }
            WireValidator.properties(payload, fields, "payload")
            JsonAudit.scalars(payload)
        }
}
