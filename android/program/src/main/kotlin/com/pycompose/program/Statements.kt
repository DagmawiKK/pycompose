package com.pycompose.program

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.longOrNull

/**
 * What one kind of statement program may do -- a drawing, a layout -- judged exactly as
 * Python's `ProgramKind` judges it.
 *
 * @property result The program's `result`.
 * @property head The arguments the host gives, before any the app binds.
 * @property calls Each call's argument types.
 * @property limits How large a program and its loops may be.
 * @property children Whether a loop may run once per child; the count is the last head argument.
 * @property ops Operations the kind's expressions add, and the frame slots they read.
 */
class ProgramKind internal constructor(
    val result: String,
    val head: List<String>,
    val calls: Map<String, List<String>>,
    val limits: Limits,
    val children: Boolean = false,
    internal val ops: KindOps = KindOps(),
)

/**
 * How large a statement program and its loops may be.
 *
 * @property nodes How many expression nodes one program may hold.
 * @property repeat The largest count one literal loop may run.
 * @property loops How deeply loops may nest.
 * @property budget How many calls one frame may make, counted through loops; null for no bound.
 */
data class Limits(
    val nodes: Int,
    val repeat: Int,
    val loops: Int,
    val budget: Int? = null,
)

/**
 * Operations a program kind adds to the catalog's, with what each means on the host.
 *
 * @property signatures Each operation's result type, by its arguments' types.
 * @property term What an operation means, given its argument terms and where the kind's
 *   reserved frame slots start (after every argument).
 * @property reserved Frame slots the host fills after the arguments, which [term] reads.
 */
internal class KindOps(
    val signatures: Map<String, Map<List<String>, String>> = emptyMap(),
    val reserved: Int = 0,
    val term: (
        String,
        List<Term>,
        Int,
    ) -> Term = { op, _, _ -> error("Program op $op has no meaning here") },
)

/**
 * A checked statement program: its steps and the frame they run in. A run costs at most what
 * the checker bounded, or one pass of a loop per child the host has.
 *
 * @property signature The host's arguments, then the bound arguments' types.
 */
class StatementProgram internal constructor(
    val signature: Signature,
    private val body: List<Step>,
    private val frameSize: Int,
) {
    /**
     * Run the program once.
     *
     * @param args The host's arguments, then the bound ones.
     * @param reserved What fills the kind's reserved slots, after the arguments.
     * @param call Receives each call made, by name, with its arguments, in order.
     */
    internal fun run(
        args: List<Any>,
        reserved: List<Any>,
        call: (String, List<Any>) -> Unit,
    ) {
        require(args.size == signature.params.size) { "Program takes ${signature.params.size}" }
        val frame = Array<Any>(frameSize) { 0L }
        args.forEachIndexed { index, value -> frame[index] = value }
        reserved.forEachIndexed { index, value -> frame[args.size + index] = value }
        body.forEach { it.run(frame, call) }
    }
}

/** One statement of a checked body. */
internal sealed interface Step {
    fun run(
        frame: Array<Any>,
        call: (String, List<Any>) -> Unit,
    )

    class Call(
        val name: String,
        val args: List<Term>,
    ) : Step {
        override fun run(
            frame: Array<Any>,
            call: (String, List<Any>) -> Unit,
        ) = call(name, args.map { it.eval(frame) })
    }

    class Branch(
        val test: Term,
        val then: List<Step>,
        val otherwise: List<Step>,
    ) : Step {
        override fun run(
            frame: Array<Any>,
            call: (String, List<Any>) -> Unit,
        ) = (if (test.eval(frame) as Boolean) then else otherwise).forEach { it.run(frame, call) }
    }

    class Repeat(
        val count: Term,
        val slot: Int,
        val body: List<Step>,
    ) : Step {
        override fun run(
            frame: Array<Any>,
            call: (String, List<Any>) -> Unit,
        ) {
            for (index in 0 until count.eval(frame) as Long) {
                frame[slot] = index
                body.forEach { it.run(frame, call) }
            }
        }
    }

    class Store(
        val slot: Int,
        val value: Term,
    ) : Step {
        override fun run(
            frame: Array<Any>,
            call: (String, List<Any>) -> Unit,
        ) {
            frame[slot] = value.eval(frame)
        }
    }
}

/** Statement programs' wire form, judged exactly as Python's validator judges it. */
object Statements {
    private val types = setOf("integer", "number", "boolean")

    /**
     * Check one statement program and build it.
     *
     * @param value The `{"type": "program", ...}` object.
     * @param functions The catalog's operations, for the expressions.
     * @param kind What the program may do.
     * @return The program, ready to run.
     */
    fun read(
        value: JsonObject,
        functions: FunctionContract,
        kind: ProgramKind,
    ): StatementProgram {
        require(value.keys == setOf("type", "params", "result", "body")) {
            "A program is {type: program, params, result, body}"
        }
        val params = (value["params"] as? JsonArray)?.map { (it as? JsonPrimitive)?.content }
        require(
            (value["type"] as? JsonPrimitive)?.content == "program" &&
                (value["result"] as? JsonPrimitive)?.content == kind.result &&
                params != null &&
                params.take(kind.head.size) == kind.head &&
                params.size <= functions.arguments &&
                params.all { it in types },
        ) { "A ${kind.result} program takes ${kind.head}, then types" }
        val signature = Signature(params.map(::checkNotNull), kind.result)
        val check = Check(signature, functions, kind)
        val body = check.block(value.getValue("body"), 1)
        return StatementProgram(signature, body, check.localBase + check.widest)
    }

    /**
     * Check what a prop runs and build it: a program of the host's arguments, or
     * `{"type": "bound", "program": ..., "args": [...]}` binding the parameters after them.
     *
     * @param value The prop's wire value, its program in place.
     * @param functions The catalog's operations, for the expressions.
     * @param kind What the program may do.
     * @return The program and the values bound to it.
     */
    fun bound(
        value: JsonObject,
        functions: FunctionContract,
        kind: ProgramKind,
    ): Pair<StatementProgram, List<Any>> {
        val bound = (value["type"] as? JsonPrimitive)?.content == "bound"
        require(!bound || value.keys == setOf("type", "program", "args")) {
            "A bound program is {type: bound, program, args}"
        }
        val program = if (bound) value["program"] as? JsonObject else value
        val args = if (bound) value["args"] as? JsonArray else JsonArray(emptyList())
        require(program != null && args != null) { "A bound program holds a program and args" }
        val read = read(program, functions, kind)
        val rest = read.signature.params.drop(kind.head.size)
        require(args.size == rest.size) { "A ${kind.result} needs ${rest.size} bound arguments" }
        return read to args.zip(rest, ::argument)
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

    private class Check(
        signature: Signature,
        functions: FunctionContract,
        val kind: ProgramKind,
    ) {
        val loopBase = signature.params.size + kind.ops.reserved
        val localBase = loopBase + kind.limits.loops
        val expressions =
            Functions.Walk(
                signature.params,
                functions,
                kind.limits.nodes,
                loopBase,
                localBase,
                kind.ops,
            )
        var calls = 0L

        /** The most locals open at once, which sizes the frame. */
        var widest = 0

        fun block(
            statements: JsonElement,
            times: Long,
        ): List<Step> {
            require(statements is JsonArray) { "A program's body is a list of statements" }
            val opened = expressions.locals.size
            val steps = statements.map { statement(it, times) }
            while (expressions.locals.size >
                opened
            ) {
                expressions.locals.removeAt(expressions.locals.lastIndex)
            }
            return steps
        }

        private fun statement(
            node: JsonElement,
            times: Long,
        ): Step {
            require(node is JsonObject) { "A statement is an object" }
            return when (node.keys) {
                setOf("call", "args") -> call(node, times)
                setOf("if", "then", "else") ->
                    Step.Branch(
                        expect(node.getValue("if"), "boolean", "an if's test"),
                        block(node.getValue("then"), times),
                        block(node.getValue("else"), times),
                    )
                setOf("repeat", "body") -> repeat(node, times)
                setOf("let") -> let(node.getValue("let"))
                setOf("set", "value") -> set(node)
                else -> error("Unknown statement ${node.keys.sorted()}")
            }
        }

        private fun call(
            node: JsonObject,
            times: Long,
        ): Step {
            val name = (node["call"] as? JsonPrimitive)?.content
            val wanted = kind.calls[name]
            val args = node["args"] as? JsonArray
            require(wanted != null && args != null) { "Unknown ${kind.result} call $name" }
            require(args.size == wanted.size) { "$name takes ${wanted.size} arguments" }
            val terms = args.zip(wanted) { arg, type -> expect(arg, type, "$name argument") }
            calls += times
            require(kind.limits.budget == null || calls <= kind.limits.budget) {
                "A frame could make more calls than allowed"
            }
            return Step.Call(checkNotNull(name), terms)
        }

        private fun repeat(
            node: JsonObject,
            times: Long,
        ): Step {
            val count = node["repeat"] as? JsonPrimitive
            val literal =
                count
                    ?.takeUnless {
                        it.isString
                    }?.longOrNull
                    ?.takeIf { count.content.all(Char::isDigit) }
            val children = count?.isString == true && count.content == "children" && kind.children
            require(
                (literal != null && literal in 0..kind.limits.repeat || children) &&
                    expressions.loops < kind.limits.loops,
            ) { "A loop runs a literal count within its limits" }
            val counted = kind.head.size - 1
            val term = if (literal != null) Term { literal } else Term { it[counted] }
            val slot = loopBase + expressions.loops
            expressions.loops += 1
            val body = block(node.getValue("body"), times * (literal ?: 1L))
            expressions.loops -= 1
            return Step.Repeat(term, slot, body)
        }

        private fun let(value: JsonElement): Step {
            val (type, term) = expressions.node(value, 1)
            val slot = localBase + expressions.locals.size
            expressions.locals += type
            widest = maxOf(widest, expressions.locals.size)
            return Step.Store(slot, term)
        }

        private fun set(node: JsonObject): Step {
            val local = (node["set"] as? JsonPrimitive)?.takeUnless { it.isString }?.longOrNull
            require(
                local != null && local in 0L until expressions.locals.size,
            ) { "No local $local to set" }
            val term = expect(node.getValue("value"), expressions.locals[local.toInt()], "a local")
            return Step.Store(localBase + local.toInt(), term)
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
