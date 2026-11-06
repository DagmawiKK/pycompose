package com.pycompose.renderer

import androidx.compose.runtime.Composable
import androidx.compose.runtime.State
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.layout.MeasurePolicy
import androidx.compose.ui.unit.Constraints
import androidx.compose.ui.unit.constrainHeight
import androidx.compose.ui.unit.constrainWidth
import com.pycompose.ir.DRAWINGS
import com.pycompose.ir.FUNCTIONS
import com.pycompose.ir.LAYOUTS
import com.pycompose.program.BoundDrawing
import com.pycompose.program.BoundFunction
import com.pycompose.program.BoundLayout
import kotlinx.serialization.json.JsonObject
import kotlin.math.roundToInt

/**
 * A draw prop's drawing and its bound arguments, read once for each value the snapshot
 * carries: a canvas redraws every frame, and the wire the parser checked does not change
 * between them.
 */
@Composable
fun rememberDrawing(wire: JsonObject): BoundDrawing =
    remember(wire) { BoundDrawing.read(wire, FUNCTIONS, DRAWINGS) }

/**
 * A function prop's program, read once for each value the snapshot carries, as the latest the
 * app stated: a holder keeps the lambda it was created with, which reads this each call.
 *
 * @param wire The prop's wire value; null leaves the native default to answer.
 * @param head The types of the arguments the host gives.
 * @param result The type the host needs back.
 */
@Composable
fun rememberFunction(
    wire: JsonObject?,
    head: List<String>,
    result: String,
): State<BoundFunction?> =
    rememberUpdatedState(
        remember(wire) {
            wire?.let { BoundFunction.read(it, head, result, FUNCTIONS) }
        },
    )

/**
 * A layout prop's program as the native measure policy, read once for each value the snapshot
 * carries. Each child is measured within the layout's largest size, then the program places
 * it; a size it states beyond the constraints is held to them.
 */
@Composable
fun rememberMeasurePolicy(wire: JsonObject): MeasurePolicy =
    remember(wire) {
        val layout = BoundLayout.read(wire, FUNCTIONS, LAYOUTS)
        MeasurePolicy { measurables, constraints ->
            val loose = constraints.copy(minWidth = 0, minHeight = 0)
            val placeables = measurables.map { it.measure(loose) }
            val sizes = DoubleArray(placeables.size * 2)
            placeables.forEachIndexed { index, placeable ->
                sizes[2 * index] = placeable.width.toDouble()
                sizes[2 * index + 1] = placeable.height.toDouble()
            }
            val placements =
                layout.measure(
                    largest(constraints.maxWidth),
                    largest(constraints.maxHeight),
                    sizes,
                )
            val width = constraints.constrainWidth(px(placements.width, constraints.minWidth))
            val height = constraints.constrainHeight(px(placements.height, constraints.minHeight))
            layout(width, height) {
                placeables.forEachIndexed { index, placeable ->
                    if (placements.placed[index]) {
                        placeable.place(
                            placements.x[index].roundToInt(),
                            placements.y[index].roundToInt(),
                        )
                    }
                }
            }
        }
    }

/** A constraint's largest size as the program reads it: unbounded is infinite. */
private fun largest(max: Int): Double =
    if (max ==
        Constraints.Infinity
    ) {
        Double.POSITIVE_INFINITY
    } else {
        max.toDouble()
    }

/** A stated size in whole px; one that is not finite falls back to [fallback]. */
private fun px(
    size: Double,
    fallback: Int,
): Int = if (size.isFinite()) size.roundToInt().coerceAtLeast(0) else fallback
