package com.pycompose.renderer

import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.lerp
import com.pycompose.program.ColourTerm
import com.pycompose.program.colour
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * Evaluate an expression the app bound to a colour prop, or null for a colour value.
 *
 * The language evaluates the numbers; the colours are mixed here, in Compose's colour space.
 * Both validators checked the wire form; evaluation still degrades to the prop's fallback.
 *
 * @param wire The prop's tagged object.
 * @return The colour, or null when [wire] is not an expression or cannot evaluate.
 */
@Composable
fun RenderContext.expressionColor(wire: JsonObject): Color? {
    if ((wire["type"] as? JsonPrimitive)?.content != "expression") return null
    val streams = renderer.streams
    return runCatching {
        when (
            val term =
                colour(
                    wire.getValue("node") as JsonObject,
                ) { node, name -> streams[node]?.get(name)?.invoke() }
        ) {
            is ColourTerm.Alpha ->
                Color(
                    term.argb,
                ).let { it.copy(alpha = it.alpha * term.fraction) }
            is ColourTerm.Mix -> lerp(Color(term.from), Color(term.to), term.fraction)
        }
    }.getOrNull()
}
