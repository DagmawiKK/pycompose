package com.pycompose.program

import kotlinx.serialization.json.JsonObject

/**
 * What the catalog lets a layout program do: its calls, the operations reading its children's
 * measured sizes, and its limits.
 *
 * @property nodes How many expression nodes one program may hold.
 * @property repeat The largest count one literal loop may run.
 * @property loops How deeply loops may nest.
 * @property calls Each call's argument types: `place` and `size`.
 * @property signatures The operations a layout's expressions add, by signature.
 */
data class LayoutContract(
    val nodes: Int,
    val repeat: Int,
    val loops: Int,
    val calls: Map<String, List<String>>,
    val signatures: Map<String, Map<List<String>, String>>,
)

/**
 * What one layout pass decided: its size, and where it placed each child; a child it never
 * placed is not shown.
 *
 * @property width The layout's width, in px; 0 when it stated none.
 * @property height Its height.
 * @property x Each child's left edge.
 * @property y Each child's top edge.
 * @property placed Whether each child was placed.
 */
class Placements internal constructor(
    val width: Double,
    val height: Double,
    val x: DoubleArray,
    val y: DoubleArray,
    val placed: BooleanArray,
)

/**
 * What a `Layout` places with: a layout program, and the values bound to the parameters after
 * the measured ones.
 */
class BoundLayout internal constructor(
    private val program: StatementProgram,
    private val args: List<Any>,
) {
    /**
     * Place children already measured.
     *
     * @param maxWidth The largest width the layout may take, in px.
     * @param maxHeight The largest height.
     * @param sizes Each child's measured width then height, in order.
     * @return The layout's size and its placements.
     */
    fun measure(
        maxWidth: Double,
        maxHeight: Double,
        sizes: DoubleArray,
    ): Placements {
        val count = sizes.size / 2
        val x = DoubleArray(count)
        val y = DoubleArray(count)
        val placed = BooleanArray(count)
        var width = 0.0
        var height = 0.0
        program.run(
            listOf(maxWidth, maxHeight, count.toLong()) + args,
            listOf(sizes),
        ) { name, values ->
            if (name == "size") {
                width = values[0] as Double
                height = values[1] as Double
            } else {
                // The last placement of a child stands; one out of range places nothing.
                val index =
                    (values[0] as Long).takeIf { it in 0 until count }?.toInt() ?: return@run
                x[index] = values[1] as Double
                y[index] = values[2] as Double
                placed[index] = true
            }
        }
        return Placements(width, height, x, y, placed)
    }

    companion object {
        private val measured = listOf("number", "number", "integer")

        /** What a layout program may do under [contract]: its sizes ride one reserved slot. */
        fun kind(contract: LayoutContract): ProgramKind {
            val ops =
                KindOps(contract.signatures, reserved = 1) { op, terms, sizes ->
                    val offset = if (op == "childWidth") 0 else 1
                    val index = terms.single()
                    Term { frame ->
                        val values = frame[sizes] as DoubleArray
                        val child = index.eval(frame) as Long
                        if (child in
                            0 until values.size / 2
                        ) {
                            values[(2 * child + offset).toInt()]
                        } else {
                            0.0
                        }
                    }
                }
            return ProgramKind(
                "layout",
                measured,
                contract.calls,
                Limits(contract.nodes, contract.repeat, contract.loops),
                children = true,
                ops = ops,
            )
        }

        /**
         * Check what a `Layout` places with and build it: a layout program, or one bound.
         *
         * @param value The layout prop's wire value, its program in place.
         * @param functions The catalog's operations, for the expressions.
         * @param contract The catalog's layout calls, operations and limits.
         * @return The layout with its arguments bound.
         */
        fun read(
            value: JsonObject,
            functions: FunctionContract,
            contract: LayoutContract,
        ): BoundLayout {
            val (program, args) = Statements.bound(value, functions, kind(contract))
            return BoundLayout(program, args)
        }
    }
}
