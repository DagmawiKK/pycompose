package com.pycompose.renderer

import androidx.compose.material3.ColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.lerp
import com.pycompose.program.ColourTerm
import com.pycompose.program.colour
import com.pycompose.renderer.generated.ValueResolver
import kotlinx.serialization.json.JsonElement
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
fun RenderContext.expressionColor(wire: JsonObject): Color? =
    expressionColor(wire, renderer.streams)

/**
 * Evaluate a colour expression over [streams], or null for a colour value; pure, so a draw
 * block may call it.
 *
 * @param wire The prop's tagged object.
 * @param streams The streams the snapshot's holders and gestures publish.
 * @return The colour, or null when [wire] is not an expression or cannot evaluate.
 */
fun expressionColor(
    wire: JsonObject,
    streams: Streams,
): Color? {
    if ((wire["type"] as? JsonPrimitive)?.content != "expression") return null
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

/**
 * A modifier's colour argument: an expression over [streams], or a colour value whose theme
 * role reads [scheme], captured in composition.
 *
 * @param value The argument's wire value.
 * @param streams The streams the snapshot publishes.
 * @param scheme The theme's colours.
 * @return The colour.
 */
fun colorValue(
    value: JsonElement,
    streams: Streams,
    scheme: ColorScheme,
): Color =
    (value as? JsonObject)?.let { expressionColor(it, streams) }
        ?: ValueResolver.color(value, scheme).getOrThrow()
