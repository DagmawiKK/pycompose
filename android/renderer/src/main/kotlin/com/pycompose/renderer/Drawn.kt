package com.pycompose.renderer

import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import com.pycompose.ir.DRAWINGS
import com.pycompose.ir.FUNCTIONS
import com.pycompose.program.BoundDrawing
import kotlinx.serialization.json.JsonObject

/**
 * A draw prop's drawing and its bound arguments, read once for each value the snapshot
 * carries: a canvas redraws every frame, and the wire the parser checked does not change
 * between them.
 */
@Composable
fun rememberDrawing(wire: JsonObject): BoundDrawing =
    remember(wire) { BoundDrawing.read(wire, FUNCTIONS, DRAWINGS) }
