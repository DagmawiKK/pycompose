package com.pycompose.program

import kotlinx.serialization.json.JsonObject

/**
 * What a canvas draws with: a drawing, and the values bound to the parameters after the
 * canvas's size.
 *
 * @property drawing The checked program.
 */
class BoundDrawing internal constructor(
    val drawing: Drawing,
    private val args: List<Any>,
) {
    /**
     * Draw one frame.
     *
     * @param width The canvas's width, in px.
     * @param height Its height, in px.
     * @param draw Receives each draw call, in order.
     */
    fun draw(
        width: Double,
        height: Double,
        draw: (DrawCall) -> Unit,
    ) = drawing.program.run(listOf(width, height) + args, emptyList()) { name, values ->
        draw(DrawCall(name, values))
    }

    companion object {
        /**
         * Check what a canvas draws with and build it: a drawing of its size, or one bound.
         *
         * @param value The draw prop's wire value, its program in place.
         * @param functions The catalog's operations, for the expressions.
         * @param contract The catalog's draw calls and limits.
         * @return The drawing with its arguments bound.
         */
        fun read(
            value: JsonObject,
            functions: FunctionContract,
            contract: DrawContract,
        ): BoundDrawing {
            val (program, args) = Statements.bound(value, functions, Drawings.kind(contract))
            return BoundDrawing(Drawing(program), args)
        }
    }
}
