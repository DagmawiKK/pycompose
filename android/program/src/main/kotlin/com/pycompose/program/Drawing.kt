package com.pycompose.program

import kotlinx.serialization.json.JsonObject

/**
 * What the catalog lets a draw program do: the draw calls the pin's `DrawScope` declares, and
 * how much one frame may draw.
 *
 * @property nodes How many expression nodes one program may hold.
 * @property draws How many draw calls one frame may make, counted through its loops.
 * @property repeat The largest count one loop may run.
 * @property loops How deeply loops may nest.
 * @property calls Each draw call's argument types, in order.
 */
data class DrawContract(
    val nodes: Int,
    val draws: Int,
    val repeat: Int,
    val loops: Int,
    val calls: Map<String, List<String>>,
)

/**
 * One draw a program asks for: the call, and its arguments typed as the call's table says
 * (Long, Double or Boolean).
 *
 * @property name The draw call's program name, such as `circle`.
 * @property args Its arguments, in the table's order.
 */
class DrawCall(
    val name: String,
    val args: List<Any>,
)

/**
 * A checked draw program, ready to draw: a frame's draw calls from the canvas's size and any
 * arguments bound to it.
 *
 * @property program The checked statements.
 */
class Drawing internal constructor(
    internal val program: StatementProgram,
) {
    /** The canvas's width and height, then the bound arguments' types. */
    val signature: Signature get() = program.signature

    /**
     * Run the program once.
     *
     * @param args The canvas's width and height, then the bound arguments.
     * @param draw Receives each draw call, in order.
     */
    fun draw(
        vararg args: Any,
        draw: (DrawCall) -> Unit,
    ) = program.run(args.asList(), emptyList()) { name, values -> draw(DrawCall(name, values)) }
}

/** A draw program's wire form, judged exactly as Python's validator judges it. */
object Drawings {
    private val canvas = listOf("number", "number")

    /** What a draw program may do under [contract]. */
    fun kind(contract: DrawContract): ProgramKind =
        ProgramKind(
            "draw",
            canvas,
            contract.calls,
            Limits(contract.nodes, contract.repeat, contract.loops, budget = contract.draws),
        )

    /**
     * Check one draw program and build it.
     *
     * @param value The `{"type": "program", "result": "draw", ...}` object.
     * @param functions The catalog's operations, for the expressions.
     * @param contract The catalog's draw calls and limits.
     * @return The program, ready to draw.
     */
    fun read(
        value: JsonObject,
        functions: FunctionContract,
        contract: DrawContract,
    ): Drawing = Drawing(Statements.read(value, functions, kind(contract)))
}
