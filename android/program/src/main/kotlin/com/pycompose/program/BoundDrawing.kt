package com.pycompose.program

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.longOrNull

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
    ) = drawing.draw(width, height, args, draw)

    companion object {
        private val canvas = listOf("number", "number")

        /**
         * Check what a canvas draws with and build it: a drawing of its size, or
         * `{"type": "bound", "program": ..., "args": [...]}` binding the parameters after it.
         *
         * @param value The draw prop's wire value.
         * @param functions The catalog's operations, for the expressions.
         * @param contract The catalog's draw calls and limits.
         * @return The drawing with its arguments bound.
         */
        fun read(
            value: JsonObject,
            functions: FunctionContract,
            contract: DrawContract,
        ): BoundDrawing {
            val bound = (value["type"] as? JsonPrimitive)?.content == "bound"
            require(!bound || value.keys == setOf("type", "program", "args")) {
                "A bound drawing is {type: bound, program, args}"
            }
            val program = if (bound) value["program"] as? JsonObject else value
            val args = if (bound) value["args"] as? JsonArray else JsonArray(emptyList())
            require(program != null && args != null) { "A bound drawing holds a program and args" }
            val drawing = Drawings.read(program, functions, contract)
            val rest = drawing.signature.params.drop(canvas.size)
            require(args.size == rest.size) { "A drawing needs ${rest.size} bound arguments" }
            return BoundDrawing(drawing, args.zip(rest, ::argument))
        }

        /** One bound argument, as its parameter's type holds it in the frame. */
        private fun argument(
            arg: JsonElement,
            type: String,
        ): Any {
            val primitive = (arg as? JsonPrimitive)?.takeUnless { it.isString }
            val whole = primitive?.content?.none { it == '.' || it == 'e' || it == 'E' } == true
            val value: Any? =
                when (type) {
                    "boolean" -> primitive?.booleanOrNull
                    "integer" -> primitive?.longOrNull?.takeIf { whole }
                    else ->
                        primitive?.doubleOrNull?.takeIf {
                            it.isFinite() &&
                                primitive.booleanOrNull == null
                        }
                }
            return requireNotNull(value) { "A bound argument is a $type" }
        }
    }
}
