package com.pycompose.ir

import com.pycompose.ir.generated.UiNode
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import java.util.Collections
import java.util.IdentityHashMap

/**
 * Per-pass results keyed by object identity; each pass keeps exactly what it used.
 *
 * A patched snapshot shares every unchanged subtree with the one before it, so
 * the same `JsonObject` arriving again means the same content, and its result
 * can be reused. Holding last pass's keys bounds the memo by the tree it saw.
 */
internal class IdentityMemo<V : Any> {
    private var previous = IdentityHashMap<Any, V>()
    private var current = IdentityHashMap<Any, V>()

    fun start() {
        previous = current
        current = IdentityHashMap()
    }

    fun reset() {
        previous = IdentityHashMap()
        current = IdentityHashMap()
    }

    operator fun get(key: Any): V? = (current[key] ?: previous[key])?.also { current[key] = it }

    fun has(key: Any): Boolean = key in current || key in previous

    operator fun set(
        key: Any,
        value: V,
    ) {
        current[key] = value
    }
}

/**
 * Decodes a node tree, reusing the node decoded for a subtree seen last pass.
 *
 * A subtree holding nothing reusable is decoded in one call, which is what a
 * whole snapshot always is. Only a node with a reusable descendant -- an
 * ancestor of what a patch changed -- is decoded on its own, with its children
 * decoded (or reused) apart and attached. An unchanged subtree is therefore the
 * same [UiNode] it was, and the renderer's equality checks short-circuit on it.
 */
internal class NodeDecoder(
    private val json: Json,
) {
    private val memo = IdentityMemo<UiNode>()

    fun reset() = memo.reset()

    fun decode(root: JsonObject): UiNode {
        memo.start()
        val reusing = reusing(root)
        val decoded = ArrayDeque<UiNode>()
        val pending = ArrayDeque<Pair<JsonObject, Boolean>>()
        pending.addLast(root to true)
        while (pending.isNotEmpty()) {
            val (element, entering) = pending.removeLast()
            val reused = if (entering) memo[element] else null
            when {
                reused != null -> decoded.addLast(reused)
                entering && element !in reusing -> decoded.addLast(whole(element))
                entering -> {
                    pending.addLast(element to false)
                    children(element).asReversed().forEach { pending.addLast(it to true) }
                }
                else -> decoded.addLast(attached(element, decoded))
            }
        }
        return decoded.single()
    }

    /** Every element that is reused or has a reused descendant, found without decoding. */
    private fun reusing(root: JsonObject): Set<JsonObject> {
        val marked = Collections.newSetFromMap(IdentityHashMap<JsonObject, Boolean>())
        val pending = ArrayDeque<Pair<JsonObject, Boolean>>()
        pending.addLast(root to true)
        while (pending.isNotEmpty()) {
            val (element, entering) = pending.removeLast()
            when {
                memo.has(element) -> marked += element
                entering -> {
                    pending.addLast(element to false)
                    children(element).forEach { pending.addLast(it to true) }
                }
                children(element).any { it in marked } -> marked += element
            }
        }
        return marked
    }

    /** A subtree with nothing to reuse, decoded in one call and indexed for next pass. */
    private fun whole(element: JsonObject): UiNode {
        val node = json.decodeFromJsonElement(UiNode.serializer(), element)
        val pending = ArrayDeque<Pair<JsonObject, UiNode>>()
        pending.addLast(element to node)
        while (pending.isNotEmpty()) {
            val (source, decoded) = pending.removeLast()
            memo[source] = decoded
            children(source).zip(decoded.children).forEach(pending::addLast)
        }
        return node
    }

    /** A node whose children were decoded apart, attached in order. */
    private fun attached(
        element: JsonObject,
        decoded: ArrayDeque<UiNode>,
    ): UiNode {
        val own = List(children(element).size) { decoded.removeLast() }.asReversed()
        // Emptied rather than removed: a leaf that names children must still fail
        // strict decoding, as it does when decoded whole.
        val bare = JsonObject(element + ("children" to JsonArray(emptyList())))
        val node = json.decodeFromJsonElement(UiNode.serializer(), bare).withChildren(own)
        memo[element] = node
        return node
    }

    private fun children(element: JsonObject): List<JsonObject> =
        (element["children"] as? JsonArray)?.map { it as JsonObject } ?: emptyList()
}
