package com.pycompose.program

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.doubleOrNull

/** Reads one holder's stream by (holder node id, stream name); null when it is not composed. */
typealias StreamReader = (String, String) -> Float?

/**
 * What a colour expression evaluates to, before a renderer turns it into a colour.
 *
 * Mixing happens in the renderer's colour space, so the language stops at the colours and the
 * fraction between them; each colour is 0xAARRGGBB.
 */
sealed interface ColourTerm {
    /** [argb] with its alpha scaled by [fraction]. */
    data class Alpha(
        val argb: Int,
        val fraction: Float,
    ) : ColourTerm

    /** The colour [fraction] of the way from [from] to [to]. */
    data class Mix(
        val from: Int,
        val to: Int,
        val fraction: Float,
    ) : ColourTerm
}

/**
 * Evaluate a checked colour expression's node.
 *
 * @param node The expression's `node`, already validated as a colour.
 * @param read The streams a holder publishes; one not composed yet reads as at rest.
 * @return The colours and the fraction, clamped to 0..1.
 */
fun colour(
    node: JsonObject,
    read: StreamReader,
): ColourTerm {
    val argument = (node.getValue("args") as JsonArray)[0] as JsonObject
    val fraction = number(argument, read).coerceIn(0f, 1f)
    return when ((node["op"] as JsonPrimitive).content) {
        "alpha" ->
            ColourTerm.Alpha(
                argb((node.getValue("color") as JsonPrimitive).content),
                fraction,
            )
        else -> {
            val colors =
                (
                    node.getValue(
                        "colors",
                    ) as JsonArray
                ).map { argb((it as JsonPrimitive).content) }
            ColourTerm.Mix(colors[0], colors[1], fraction)
        }
    }
}

/**
 * Evaluate a checked number node.
 *
 * @param node A literal, a stream or an operation over numbers.
 * @param read The streams a holder publishes.
 * @return Its value.
 */
fun number(
    node: JsonObject,
    read: StreamReader,
): Float {
    val literal = (node["number"] as? JsonPrimitive)?.doubleOrNull
    val holder = (node["stream"] as? JsonPrimitive)?.content
    return when {
        literal != null -> literal.toFloat()
        // A holder not composed yet reads as at rest; its publishing recomposes the reader.
        holder != null -> read(holder, (node.getValue("name") as JsonPrimitive).content) ?: 0f
        else -> operation(node, read)
    }
}

private fun operation(
    node: JsonObject,
    read: StreamReader,
): Float {
    val args = (node.getValue("args") as JsonArray).map { number(it as JsonObject, read) }
    return when ((node["op"] as JsonPrimitive).content) {
        "times" -> args[0] * args[1]
        "plus" -> args[0] + args[1]
        "minus" -> args[0] - args[1]
        else -> args[0].coerceIn(args[1], args[2])
    }
}

/** `#RRGGBB` is opaque; `#AARRGGBB` carries its own alpha. */
private fun argb(value: String): Int =
    value
        .removePrefix("#")
        .padStart(OPAQUE.length, 'F')
        .toLong(HEX)
        .toInt()

private const val OPAQUE = "AARRGGBB"
private const val HEX = 16
