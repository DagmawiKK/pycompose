package com.pycompose.ir

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * Puts each program a snapshot's props name as `{"type": "ref", "hash": <hash>}` back
 * where it is named, from the snapshot's `programs` section, so validation and rendering
 * read it in place.
 *
 * A snapshot carries each program once, however many props name it, and a held section is
 * kept across patches rather than sent again. A subtree naming no program keeps its identity;
 * one whose programs are the very objects it used last time is reused whole, so what a patch
 * left unchanged is still recognised downstream.
 */
internal object ProgramRefs {
    /** One subtree with its programs in place, and the programs it took, by hash. */
    internal class Inflated(
        val node: JsonObject,
        val used: Map<String, JsonElement>,
    )

    /** The snapshot with every program reference replaced by its program. */
    internal fun inflate(
        raw: JsonObject,
        memo: IdentityMemo<Inflated>,
    ): JsonObject {
        val section = (raw["metadata"] as? JsonObject)?.get("programs")
        val programs =
            section?.let { it as? JsonObject ?: error("programs must be an object") }
                ?: JsonObject(emptyMap())
        val root = raw["root"] as? JsonObject ?: error("root must be an object")
        memo.start()
        val inflated = node(root, programs, memo).node
        return if (inflated === root) raw else JsonObject(raw + ("root" to inflated))
    }

    private fun node(
        source: JsonObject,
        programs: JsonObject,
        memo: IdentityMemo<Inflated>,
    ): Inflated {
        memo[source]
            ?.takeIf { hit -> hit.used.all { (hash, program) -> programs[hash] === program } }
            ?.let { return it }
        val used = mutableMapOf<String, JsonElement>()
        val props = source["props"]
        val inflatedProps = props?.let { value(it, programs, used) }
        val children = source["children"] as? JsonArray
        val inflatedChildren =
            children?.map { child ->
                val inflated = node(child as? JsonObject ?: return@map child, programs, memo)
                used += inflated.used
                inflated.node
            }
        val changed =
            inflatedProps !== props ||
                (
                    inflatedChildren != null &&
                        inflatedChildren.indices.any { inflatedChildren[it] !== children[it] }
                )
        val node =
            if (!changed) {
                source
            } else {
                JsonObject(
                    source +
                        (inflatedProps?.let { mapOf("props" to it) } ?: emptyMap()) +
                        (
                            inflatedChildren?.let {
                                mapOf(
                                    "children" to JsonArray(it),
                                )
                            } ?: emptyMap()
                        ),
                )
            }
        return Inflated(node, used).also { memo[source] = it }
    }

    /** [element] with each reference in it replaced, or itself when it names none. */
    private fun value(
        element: JsonElement,
        programs: JsonObject,
        used: MutableMap<String, JsonElement>,
    ): JsonElement =
        when (element) {
            is JsonObject ->
                ref(element)?.let { hash ->
                    val program = programs[hash] ?: error("No program $hash in the snapshot")
                    program.also { used[hash] = it }
                } ?: element
                    .mapValues { (_, member) -> value(member, programs, used) }
                    .let { members ->
                        if (members.all { (k, v) ->
                                v === element[k]
                            }
                        ) {
                            element
                        } else {
                            JsonObject(members)
                        }
                    }
            is JsonArray ->
                element
                    .map { value(it, programs, used) }
                    .let { members ->
                        if (members.indices.all {
                                members[it] === element[it]
                            }
                        ) {
                            element
                        } else {
                            JsonArray(
                                members,
                            )
                        }
                    }
            else -> element
        }

    private fun ref(value: JsonObject): String? {
        if ((value["type"] as? JsonPrimitive)?.content != "ref") return null
        require(value.keys == setOf("type", "hash")) { "A ref is {type: ref, hash}" }
        val hash = value["hash"] as? JsonPrimitive
        return hash?.takeIf { it.isString }?.content ?: error("A ref names a hash")
    }
}
