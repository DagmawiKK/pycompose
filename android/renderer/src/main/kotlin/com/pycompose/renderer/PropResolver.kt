package com.pycompose.renderer

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.TooltipAnchorPosition
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.graphics.RectangleShape
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/** All fallible conversions are values; malformed props never throw into Compose. */
object PropResolver {
    private val horizontalValues =
        mapOf(
            "start" to Alignment.Start,
            "center" to Alignment.CenterHorizontally,
            "end" to Alignment.End,
        )
    private val verticalValues =
        mapOf(
            "top" to Alignment.Top,
            "center" to Alignment.CenterVertically,
            "bottom" to Alignment.Bottom,
        )
    private val boxValues =
        mapOf(
            "topStart" to Alignment.TopStart,
            "topCenter" to Alignment.TopCenter,
            "topEnd" to Alignment.TopEnd,
            "centerStart" to Alignment.CenterStart,
            "center" to Alignment.Center,
            "centerEnd" to Alignment.CenterEnd,
            "bottomStart" to Alignment.BottomStart,
            "bottomCenter" to Alignment.BottomCenter,
            "bottomEnd" to Alignment.BottomEnd,
        )
    private val arrangements =
        mapOf(
            "top" to Arrangement.Top,
            "center" to Arrangement.Center,
            "bottom" to Arrangement.Bottom,
            "spaceEvenly" to Arrangement.SpaceEvenly,
            "spaceBetween" to Arrangement.SpaceBetween,
            "spaceAround" to Arrangement.SpaceAround,
        )
    private val shapes: Map<String, Shape> =
        mapOf(
            "rectangle" to RectangleShape,
            "circle" to CircleShape,
            "rounded" to RoundedCornerShape(8.dp),
        )

    fun dp(value: Double): Result<Dp> =
        runCatching {
            require(value.isFinite() && value >= 0 && value <= Float.MAX_VALUE.toDouble()) {
                "Invalid dp: $value"
            }
            value.toFloat().dp
        }

    fun durationMs(value: Long): Result<Long> =
        runCatching {
            require(value >= 0) { "Negative duration" }
            value
        }

    fun horizontal(value: String): Result<Alignment.Horizontal> = enum(value, horizontalValues)

    fun vertical(value: String): Result<Alignment.Vertical> = enum(value, verticalValues)

    fun alignment(value: String): Result<Alignment> = enum(value, boxValues)

    fun arrangement(value: String): Result<Arrangement.Vertical> = enum(value, arrangements)

    fun shape(value: String): Result<Shape> = enum(value, shapes)

    /**
     * Map a wire typography name to a Material 3 style.
     *
     * Composable because it reads [MaterialTheme], so it cannot be an ordinary
     * function: the theme is only in scope during composition. Generated
     * adapters call it from a `val` declaration at the top of the lambda for
     * the same reason -- a call inside an argument list is not composable.
     */
    @Composable
    fun textStyle(
        value: String?,
        fallback: TextStyle,
    ): TextStyle =
        with(MaterialTheme.typography) {
            enum(
                value.orEmpty(),
                mapOf(
                    "bodyLarge" to bodyLarge,
                    "bodyMedium" to bodyMedium,
                    "bodySmall" to bodySmall,
                    "titleLarge" to titleLarge,
                    "titleMedium" to titleMedium,
                    "titleSmall" to titleSmall,
                    "headlineMedium" to headlineMedium,
                ),
            ).getOrDefault(fallback)
        }

    fun <T> enum(
        value: String,
        values: Map<String, T>,
    ): Result<T> =
        runCatching {
            requireNotNull(values[value]) { "Unsupported value: $value" }
        }
}

/** Experimental Material 3 tooltip positions, separate from UI scalar conversions. */
@OptIn(ExperimentalMaterial3Api::class)
object TooltipPropResolver {
    fun tooltipPosition(value: String): Result<TooltipAnchorPosition> =
        PropResolver.enum(
            value,
            mapOf(
                "above" to TooltipAnchorPosition.Above,
                "below" to TooltipAnchorPosition.Below,
                "left" to TooltipAnchorPosition.Left,
                "right" to TooltipAnchorPosition.Right,
                "start" to TooltipAnchorPosition.Start,
                "end" to TooltipAnchorPosition.End,
            ),
        )
}
