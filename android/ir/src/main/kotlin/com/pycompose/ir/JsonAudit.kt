package com.pycompose.ir

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.doubleOrNull

/** Checks information lost by tree decoding: duplicate keys and canonical scalars. */
internal object JsonAudit {
    private data class Frame(
        val keys: MutableSet<String>?,
        var expectKey: Boolean = true,
    )

    private val numberSyntax = Regex("-?(0|[1-9][0-9]*)(\\.[0-9]+)?([eE][+-]?[0-9]+)?")

    fun uniqueKeys(
        source: String,
        json: Json,
    ) {
        val frames = ArrayDeque<Frame>()
        var index = 0
        while (index < source.length) {
            when (source[index]) {
                '{' -> frames.addLast(Frame(mutableSetOf()))
                '[' -> frames.addLast(Frame(null))
                '}', ']' -> {
                    require(frames.isNotEmpty()) { "Unbalanced JSON container" }
                    frames.removeLast()
                }
                ',' -> frames.lastOrNull()?.let { it.expectKey = it.keys != null }
                '"' -> {
                    val end = stringEnd(source, index)
                    val frame = frames.lastOrNull()
                    if (frame?.keys != null && frame.expectKey) {
                        val key = json.decodeFromString<String>(source.substring(index, end + 1))
                        require(frame.keys.add(key)) { "Duplicate JSON key: $key" }
                        frame.expectKey = false
                    }
                    index = end
                }
            }
            index++
        }
    }

    private fun stringEnd(
        source: String,
        start: Int,
    ): Int {
        var index = start + 1
        while (index < source.length) {
            when (source[index]) {
                '\\' -> index += 2
                '"' -> return index
                else -> index++
            }
        }
        error("Unterminated JSON string")
    }

    /** Containers audited last pass are the same content when they recur; skip them. */
    fun scalars(
        root: JsonElement,
        memo: IdentityMemo<Unit>? = null,
    ) {
        val pending = ArrayDeque<JsonElement>()
        pending.addLast(root)
        while (pending.isNotEmpty()) {
            val value = pending.removeLast()
            if (value !is JsonPrimitive && memo != null) {
                if (memo[value] != null) continue
                memo[value] = Unit
            }
            when (value) {
                is JsonObject -> {
                    value.keys.forEach(::unicode)
                    value.values.forEach(pending::addLast)
                }
                is JsonArray -> value.forEach(pending::addLast)
                is JsonPrimitive -> {
                    if (value.isString) unicode(value.content) else number(value)
                }
            }
        }
    }

    private fun number(value: JsonPrimitive) {
        val text = value.content
        if (text in setOf("true", "false", "null")) return
        require(numberSyntax.matches(text)) { "Invalid JSON scalar: $text" }
        val integer = text.none { it == '.' || it == 'e' || it == 'E' }
        require(integer || value.doubleOrNull?.isFinite() == true) { "Non-finite JSON number" }
    }

    private fun unicode(value: String) {
        var index = 0
        while (index < value.length) {
            if (value[index].isHighSurrogate()) {
                require(index + 1 < value.length && value[index + 1].isLowSurrogate()) {
                    "Unpaired Unicode surrogate"
                }
                index += 2
            } else {
                require(!value[index].isLowSurrogate()) { "Unpaired Unicode surrogate" }
                index++
            }
        }
    }
}
