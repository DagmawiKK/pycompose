package com.pycompose.ir

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject

/**
 * Lowers a snapshot's intents to the handles the host keys on (see [Intents]).
 *
 * Each lowered intent whose handler states a contract becomes a binding in the
 * host-internal `actionBindings` section, and the echo list becomes a map from handle
 * to number. A subtree with no intent keeps its identity, so what a patch left
 * unchanged is still recognised downstream.
 */
internal object IntentLowering {
    /**
     * The snapshot with every intent lowered to its handle.
     *
     * Each lowered intent whose handler states a contract becomes a binding in the
     * host-internal `actionBindings` section, and the echo list becomes a map from
     * handle to number. A subtree with no intent keeps its identity, so what a patch
     * left unchanged is still recognised downstream.
     */
    internal fun lower(
        raw: JsonObject,
        memo: IdentityMemo<Lowered>,
    ): JsonObject {
        val metadata = raw["metadata"] as? JsonObject
        require(
            metadata?.containsKey("actionBindings") != true,
        ) { "actionBindings is not wire data" }
        val root = raw["root"] as? JsonObject ?: error("root must be an object")
        memo.start()
        val lowered = node(root, memo)
        val bindings = bindings(lowered.intents, metadata)
        val echoes = metadata?.get("echoes")?.let(::echoes)
        val sections = mutableMapOf<String, JsonElement>()
        metadata?.let { sections += it }
        if (bindings.isNotEmpty()) sections["actionBindings"] = JsonObject(bindings)
        echoes?.let { sections["echoes"] = it }
        if (lowered.node === root && sections == metadata.orEmpty()) return raw
        return JsonObject(raw + ("root" to lowered.node) + ("metadata" to JsonObject(sections)))
    }

    /** The host-internal binding for each lowered intent whose handler states a contract. */
    private fun bindings(
        intents: Map<String, JsonObject>,
        metadata: JsonObject?,
    ): Map<String, JsonObject> {
        val contracts =
            metadata
                ?.get(
                    "intents",
                )?.let { it as? JsonObject ?: error("intents must be an object") }
                ?: JsonObject(emptyMap())
        return intents
            .mapNotNull { (handle, intent) ->
                val name = (intent["intent"] as? JsonPrimitive)?.content
                val contract = name?.let { contracts[it] as? JsonObject } ?: return@mapNotNull null
                require(contract.keys == setOf("payload")) { "Invalid intent contract" }
                handle to
                    buildJsonObject {
                        put("handlerId", JsonPrimitive(name))
                        put("payload", contract.getValue("payload"))
                        put("bound", intent["fields"] ?: JsonObject(emptyMap()))
                    }
            }.toMap()
    }

    /** One lowered subtree and the intents it carries, by handle. */
    internal class Lowered(
        val node: JsonObject,
        val intents: Map<String, JsonObject>,
    )

    private fun node(
        source: JsonObject,
        memo: IdentityMemo<Lowered>,
    ): Lowered {
        memo[source]?.let { return it }
        val intents = mutableMapOf<String, JsonObject>()
        val props = source["props"] as? JsonObject
        val loweredProps = props?.let { props(it, intents) }
        val children = source["children"] as? JsonArray
        val loweredChildren =
            children?.map { child ->
                val lowered = node(child as? JsonObject ?: return@map child, memo)
                intents += lowered.intents
                lowered.node
            }
        val changed =
            (loweredProps != null && loweredProps !== props) ||
                (
                    loweredChildren != null &&
                        loweredChildren.indices.any { loweredChildren[it] !== children[it] }
                )
        val result =
            if (!changed) {
                source
            } else {
                JsonObject(
                    source +
                        (loweredProps?.let { mapOf("props" to it) } ?: emptyMap()) +
                        (loweredChildren?.let { mapOf("children" to JsonArray(it)) } ?: emptyMap()),
                )
            }
        return Lowered(result, intents).also { memo[source] = it }
    }

    private fun props(
        props: JsonObject,
        intents: MutableMap<String, JsonObject>,
    ): JsonObject {
        var changed = false
        val lowered =
            props.mapValues { (name, value) ->
                when {
                    Intents.isIntent(value) -> {
                        changed = true
                        lowerIntent(value as JsonObject, intents)
                    }
                    name == "modifier" && value is JsonObject -> {
                        val modifier = modifier(value, intents)
                        if (modifier !== value) changed = true
                        modifier
                    }
                    else -> value
                }
            }
        return if (changed) JsonObject(lowered) else props
    }

    private fun modifier(
        value: JsonObject,
        intents: MutableMap<String, JsonObject>,
    ): JsonObject {
        val operations = value["operations"] as? JsonArray
        if (operations == null ||
            operations.none { Intents.isIntent((it as? JsonObject)?.get("onClick")) }
        ) {
            return value
        }
        val lowered =
            operations.map { operation ->
                val click = (operation as? JsonObject)?.get("onClick")
                if (Intents.isIntent(click)) {
                    JsonObject(
                        operation as JsonObject +
                            ("onClick" to lowerIntent(click as JsonObject, intents)),
                    )
                } else {
                    operation
                }
            }
        return JsonObject(value + ("operations" to JsonArray(lowered)))
    }

    private fun lowerIntent(
        intent: JsonObject,
        intents: MutableMap<String, JsonObject>,
    ): JsonPrimitive {
        val handle = Intents.handle(intent)
        intents[handle] = intent
        return JsonPrimitive(handle)
    }

    private fun echoes(value: JsonElement): JsonObject {
        val list = value as? JsonArray ?: error("echoes must be a list")
        return JsonObject(
            list.associate { entry ->
                val echo = entry as? JsonObject ?: error("An echo must be an object")
                require(
                    echo.keys == setOf("seq", "target"),
                ) { "An echo names its target and number" }
                val target = echo.getValue("target")
                val key =
                    when {
                        target is JsonPrimitive && target.isString -> target.content
                        Intents.isIntent(target) -> Intents.handle(target as JsonObject)
                        else -> error("An echo's target is an action name or an intent")
                    }
                key to echo.getValue("seq")
            },
        )
    }
}
