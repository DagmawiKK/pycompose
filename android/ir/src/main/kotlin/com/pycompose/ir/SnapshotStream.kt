package com.pycompose.ir

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.longOrNull

/**
 * The snapshot the host holds, advanced by each pulled envelope (ADR-0018).
 *
 * A full envelope replaces it. A patch applies only when its base is the serial
 * held, and rebuilds just the changed nodes and their ancestors: every other
 * subtree stays the same object, so it is neither validated nor decoded again,
 * and the renderer sees the same node it already composed. Any failure forgets
 * the held snapshot, so the next pull asks for the whole one.
 *
 * @param surface The surface this stream renders; an envelope naming another is refused.
 */
class SnapshotStream(
    private val parser: IrParser = IrParser(),
    val surface: String = MAIN_SURFACE,
) {
    /** The serial of the held snapshot, or [NONE] when the next pull must be whole. */
    var serial: Long = NONE
        private set

    private var held: JsonObject? = null

    /** Forget the held snapshot; the session behind it was replaced. */
    fun reset() {
        serial = NONE
        held = null
    }

    /** Apply one pulled envelope; a bare snapshot is accepted as a whole one with no serial. */
    fun accept(envelope: String): Result<ValidatedIr> =
        runCatching {
            val raw = parser.read(envelope)
            raw["surface"]?.let {
                require(
                    WireValidator.string(it, "surface") == surface,
                ) { "Envelope for another surface" }
            }
            val snapshot =
                when (raw["kind"]?.let { WireValidator.string(it, "kind") }) {
                    null -> raw
                    "full" -> JsonObject(raw - "kind" - "serial" - "surface")
                    "patch" -> patched(raw)
                    else -> error("Unknown envelope kind")
                }
            val result = parser.accept(snapshot)
            held = snapshot
            serial = (raw["serial"] as? JsonPrimitive)?.longOrNull ?: NONE
            result
        }.onFailure { reset() }

    private fun patched(envelope: JsonObject): JsonObject {
        val base = held
        val baseSerial = (envelope["baseSerial"] as? JsonPrimitive)?.longOrNull
        require(base != null && baseSerial == serial) { "Patch against a snapshot not held" }
        val ops = envelope["ops"] as? JsonArray ?: error("Patch ops must be an array")
        var root = base["root"] as JsonObject
        ops.forEach {
            root =
                applied(
                    root,
                    it as? JsonObject ?: error("Patch op must be an object"),
                )
        }
        val metadata = metadata(base["metadata"] as? JsonObject, envelope)
        return JsonObject(
            envelope.filterKeys { it in setOf("version", "schemaVersion") } +
                ("root" to root) +
                (if (metadata.isEmpty()) emptyMap() else mapOf("metadata" to metadata)),
        )
    }

    /**
     * The patched snapshot's metadata: the envelope's own sections and the held sections it
     * names in `keep`.
     */
    private fun metadata(
        held: JsonObject?,
        envelope: JsonObject,
    ): JsonObject {
        val kept =
            (envelope["keep"] as? JsonArray).orEmpty().associate { name ->
                val section = WireValidator.string(name, "keep")
                section to (held?.get(section) ?: error("Kept section $section is not held"))
            }
        val stated =
            envelope["metadata"]?.let { it as? JsonObject ?: error("metadata must be an object") }
                ?: JsonObject(emptyMap())
        if (kept.keys.any { it in stated }) error("A section stated both whole and kept")
        return JsonObject(stated + kept)
    }

    private fun applied(
        root: JsonObject,
        op: JsonObject,
    ): JsonObject =
        rewrite(root, op) { node ->
            when (WireValidator.string(op["op"], "op.op")) {
                "setProp" -> {
                    val props = node["props"] as? JsonObject ?: error("Missing object props")
                    val value = op["value"] ?: error("Missing op value")
                    val prop = WireValidator.string(op["prop"], "op.prop")
                    JsonObject(node + ("props" to JsonObject(props + (prop to value))))
                }
                "replaceSubtree" -> op["payload"] as? JsonObject ?: error("Missing op payload")
                else -> error("Unknown patch op")
            }
        }

    /**
     * [root] with the node [op] locates changed, its ancestors rebuilt and all else shared.
     * The op's child indices find the node; its id only confirms it, since ids carry no path.
     */
    private fun rewrite(
        root: JsonObject,
        op: JsonObject,
        change: (JsonObject) -> JsonObject,
    ): JsonObject {
        val target = WireValidator.string(op["id"], "op.id")
        val indices =
            (op["at"] as? JsonArray ?: error("op.at must be an array")).map {
                (it as? JsonPrimitive)?.content?.toIntOrNull() ?: error("op.at must hold indices")
            }
        val path = mutableListOf(root)
        for (index in indices) {
            val children = path.last()["children"] as? JsonArray ?: error("No node $target")
            path += children.getOrNull(index) as? JsonObject ?: error("No node $target")
        }
        require(WireValidator.string(path.last()["id"], "node.id") == target) { "No node $target" }
        var replaced = change(path.last())
        for (level in indices.indices.reversed()) {
            val parent = path[level]
            val children = (parent["children"] as JsonArray).toMutableList()
            children[indices[level]] = replaced
            replaced = JsonObject(parent + ("children" to JsonArray(children)))
        }
        return replaced
    }

    companion object {
        /** No snapshot held: the next pull must be whole. */
        const val NONE = -1L

        /** The one surface a session hosts until it hosts several. */
        const val MAIN_SURFACE = "main"
    }
}
