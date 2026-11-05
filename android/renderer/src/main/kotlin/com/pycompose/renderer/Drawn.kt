package com.pycompose.renderer

import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import com.pycompose.ir.DRAWINGS
import com.pycompose.ir.FUNCTIONS
import com.pycompose.program.Drawing
import com.pycompose.program.Drawings
import kotlinx.serialization.json.JsonObject

/**
 * A draw prop's program, read once for each program the snapshot carries: a canvas redraws
 * every frame, and the wire the parser already checked does not change between them.
 */
@Composable
fun rememberDrawing(wire: JsonObject): Drawing =
    remember(wire) { Drawings.read(wire, FUNCTIONS, DRAWINGS) }
