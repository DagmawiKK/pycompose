package com.pycompose.renderer

import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.pycompose.program.Expressions
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.double

/** The streams a snapshot's holders publish, by node id and stream name. */
typealias Streams = Map<String, Map<String, () -> Float>>

/**
 * The number a dp or number value states: its value, or the value an expression gives.
 *
 * A holder not composed yet reads as at rest, and the expression's own read recomposes the
 * caller as the stream moves. Both validators checked the wire form; evaluation still degrades
 * to zero rather than throwing inside composition.
 *
 * @param wire The value: a number, or an expression over holder streams.
 * @param streams The streams the snapshot's holders publish.
 * @return The number the value gives.
 */
fun numberValue(
    wire: JsonElement,
    streams: Streams,
): Double {
    if (!Expressions.isExpression(wire)) return (wire as JsonPrimitive).double
    return expressionNumber(wire as JsonObject, streams) ?: 0.0
}

/**
 * The dp a dp value states, read the same way a number is.
 *
 * @param wire The value: a number, or an expression over holder streams.
 * @param streams The streams the snapshot's holders publish.
 * @return The dp the value gives.
 */
fun dpValue(
    wire: JsonElement,
    streams: Streams,
): Dp = numberValue(wire, streams).toFloat().dp

/**
 * The number a dp or number prop states, read from the streams on screen.
 *
 * @param wire The prop's wire value: a number, or an expression over holder streams.
 * @return The number the value gives.
 */
fun RenderContext.number(wire: JsonElement): Double = numberValue(wire, renderer.streams)

/** A checked number expression's value, or null when it cannot be read. */
private fun expressionNumber(
    wire: JsonObject,
    streams: Streams,
): Double? =
    runCatching {
        com.pycompose.program
            .number(wire.getValue("node") as JsonObject) { holder, name ->
                streams[holder]?.get(name)?.invoke()
            }.toDouble()
    }.getOrNull()
