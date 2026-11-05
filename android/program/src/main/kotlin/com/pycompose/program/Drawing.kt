package com.pycompose.program

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.longOrNull

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
 * arguments bound to it. A frame costs at most what the checker bounded.
 *
 * @property signature The canvas's width and height, then the bound arguments' types.
 */
class Drawing internal constructor(
    val signature: Signature,
    private val body: List<Step>,
    private val loops: Int,
) {
    /**
     * Run the program once.
     *
     * @param args The canvas's width and height, then the bound arguments.
     * @param draw Receives each draw call, in order.
     */
    fun draw(
        vararg args: Any,
        draw: (DrawCall) -> Unit,
    ) {
        require(args.size == signature.params.size) { "Drawing takes ${signature.params.size}" }
        run(Array(args.size + loops) { args.getOrElse(it) { 0L } }, args.size, draw)
    }

    /** One frame on a canvas of this size, with [bound] after it in the frame. */
    internal fun draw(
        width: Double,
        height: Double,
        bound: List<Any>,
        draw: (DrawCall) -> Unit,
    ) {
        val given = 2 + bound.size
        val frame =
            Array(given + loops) {
                when {
                    it == 0 -> width
                    it == 1 -> height
                    it < given -> bound[it - 2]
                    else -> 0L
                }
            }
        run(frame, given, draw)
    }

    private fun run(
        frame: Array<Any>,
        base: Int,
        draw: (DrawCall) -> Unit,
    ) = body.forEach { it.run(frame, base, draw) }
}

/** One statement of a checked body. */
internal sealed interface Step {
    fun run(
        frame: Array<Any>,
        base: Int,
        draw: (DrawCall) -> Unit,
    )

    class Draw(
        val name: String,
        val args: List<Term>,
    ) : Step {
        override fun run(
            frame: Array<Any>,
            base: Int,
            draw: (DrawCall) -> Unit,
        ) = draw(DrawCall(name, args.map { it.eval(frame) }))
    }

    class Branch(
        val test: Term,
        val then: List<Step>,
        val otherwise: List<Step>,
    ) : Step {
        override fun run(
            frame: Array<Any>,
            base: Int,
            draw: (DrawCall) -> Unit,
        ) = (
            if (test.eval(
                    frame,
                ) as Boolean
            ) {
                then
            } else {
                otherwise
            }
        ).forEach { it.run(frame, base, draw) }
    }

    class Repeat(
        val count: Long,
        val loop: Int,
        val body: List<Step>,
    ) : Step {
        override fun run(
            frame: Array<Any>,
            base: Int,
            draw: (DrawCall) -> Unit,
        ) {
            for (index in 0 until count) {
                frame[base + loop] = index
                body.forEach { it.run(frame, base, draw) }
            }
        }
    }
}

/** A draw program's wire form, judged exactly as Python's validator judges it. */
object Drawings {
    private val types = setOf("integer", "number", "boolean")

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
    ): Drawing {
        require(value.keys == setOf("type", "params", "result", "body")) {
            "A program is {type: program, params, result, body}"
        }
        val params = (value["params"] as? JsonArray)?.map { (it as? JsonPrimitive)?.content }
        require(
            (value["type"] as? JsonPrimitive)?.content == "program" &&
                (value["result"] as? JsonPrimitive)?.content == "draw" &&
                params != null &&
                params.take(2) == listOf("number", "number") &&
                params.size <= functions.arguments &&
                params.all { it in types },
        ) { "A draw program takes the canvas's size, then types" }
        val signature = Signature(params.map(::checkNotNull), "draw")
        val check = Check(Functions.Walk(signature.params, functions, contract.nodes), contract)
        val body = check.block(value.getValue("body"), 1)
        return Drawing(signature, body, contract.loops)
    }

    private class Check(
        val expressions: Functions.Walk,
        val contract: DrawContract,
    ) {
        var draws = 0L

        fun block(
            statements: JsonElement,
            times: Long,
        ): List<Step> {
            require(statements is JsonArray) { "A draw program's body is a list of statements" }
            return statements.map { statement(it, times) }
        }

        private fun statement(
            node: JsonElement,
            times: Long,
        ): Step {
            require(node is JsonObject) { "A draw statement is an object" }
            return when (node.keys) {
                setOf("draw", "args") -> draw(node, times)
                setOf("if", "then", "else") ->
                    Step.Branch(
                        expect(node.getValue("if"), "boolean", "an if's test"),
                        block(node.getValue("then"), times),
                        block(node.getValue("else"), times),
                    )
                setOf("repeat", "body") -> repeat(node, times)
                else -> error("Unknown draw statement ${node.keys.sorted()}")
            }
        }

        private fun draw(
            node: JsonObject,
            times: Long,
        ): Step {
            val name = (node["draw"] as? JsonPrimitive)?.content
            val wanted = contract.calls[name]
            val args = node["args"] as? JsonArray
            require(wanted != null && args != null) { "Unknown draw call $name" }
            require(args.size == wanted.size) { "$name takes ${wanted.size} arguments" }
            val terms = args.zip(wanted) { arg, type -> expect(arg, type, "$name argument") }
            draws += times
            require(draws <= contract.draws) { "A frame could make more draws than allowed" }
            return Step.Draw(checkNotNull(name), terms)
        }

        private fun repeat(
            node: JsonObject,
            times: Long,
        ): Step {
            val count = (node["repeat"] as? JsonPrimitive)?.takeUnless { it.isString }
            val value = count?.longOrNull?.takeIf { count.content.all(Char::isDigit) }
            require(
                value != null && value in 0..contract.repeat && expressions.loops < contract.loops,
            ) { "A loop runs a literal count within its limits" }
            val loop = expressions.loops
            expressions.loops += 1
            val body = block(node.getValue("body"), times * value)
            expressions.loops -= 1
            return Step.Repeat(value, loop, body)
        }

        private fun expect(
            node: JsonElement,
            wanted: String,
            what: String,
        ): Term {
            val (type, term) = expressions.node(node, 1)
            require(type == wanted) { "$what takes a $wanted, not a $type" }
            return term
        }
    }
}
