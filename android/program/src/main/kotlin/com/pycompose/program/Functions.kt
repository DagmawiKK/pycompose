package com.pycompose.program

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.longOrNull

/**
 * What the catalog lets a value function use: its limits and its operations.
 *
 * @property depth How deeply a body may nest.
 * @property nodes How many nodes one body may hold.
 * @property arguments How many arguments a function may take.
 * @property signatures Each operation's argument types and the type it gives.
 */
data class FunctionContract(
    val depth: Int,
    val nodes: Int,
    val arguments: Int,
    val signatures: Map<String, Map<List<String>, String>>,
)

/**
 * A value function's argument types and result type, each `integer`, `number` or `boolean`.
 *
 * @property params Each argument's type, in order.
 * @property result What it returns.
 */
data class Signature(
    val params: List<String>,
    val result: String,
)

/**
 * A checked value function, ready to call: Python a parameter calls within a frame.
 *
 * Integers are Long, numbers Double and booleans Boolean, in and out. A call is total and
 * costs at most the body's size: there are no loops, and `floorDiv` and `mod` by zero give 0.
 *
 * @property signature Its argument and result types.
 */
class Function internal constructor(
    val signature: Signature,
    private val body: Term,
) {
    /**
     * Call it.
     *
     * @param args One value per argument, typed as [signature] states.
     * @return The result, typed as [signature] states.
     */
    fun call(vararg args: Any): Any {
        require(args.size == signature.params.size) { "Function takes ${signature.params.size}" }
        return body.eval(args)
    }
}

/** One node of a checked body. */
internal fun interface Term {
    fun eval(args: Array<out Any>): Any
}

/**
 * A value function's wire form, judged exactly as Python's validator judges it, and built
 * into a [Function] in the same walk.
 */
object Functions {
    private val types = setOf(INTEGER, NUMBER, BOOLEAN)

    /**
     * Check one program and build it.
     *
     * @param value The `{"type": "program", "params", "result", "body"}` object.
     * @param contract The catalog's limits and vocabulary.
     * @return The callable function.
     */
    fun read(
        value: JsonObject,
        contract: FunctionContract,
    ): Function {
        require(value.keys == setOf("type", "params", "result", "body")) {
            "A program is {type: program, params, result, body}"
        }
        val params = (value["params"] as? JsonArray)?.map { (it as? JsonPrimitive)?.content }
        val result = (value["result"] as? JsonPrimitive)?.content
        require(
            (value["type"] as? JsonPrimitive)?.content == "program" &&
                params != null &&
                params.size <= contract.arguments &&
                params.all { it in types } &&
                result in types,
        ) { "A program's params and result are types" }
        val signature = Signature(params.map(::checkNotNull), checkNotNull(result))
        val (type, body) = Walk(signature.params, contract).node(value.getValue("body"), 1)
        require(type == result) { "A program's body does not give a $result" }
        return Function(signature, body)
    }

    /**
     * Types one program's expressions and builds their terms, counting nodes against a limit.
     *
     * @property params The program's argument types; a term reads argument i at index i.
     * @property contract The catalog's operations and depth limit.
     * @property nodes How many nodes the whole program may hold.
     * @property loopBase Where loop indices start in the frame; locals follow at [localBase].
     * @property ops Operations a program kind adds, and what each means.
     */
    internal class Walk(
        val params: List<String>,
        val contract: FunctionContract,
        private val nodes: Int = contract.nodes,
        private val loopBase: Int = params.size,
        private val localBase: Int = params.size,
        private val ops: KindOps = KindOps(),
    ) {
        var count = 0

        /** How many loops enclose the expression; loop k's index is read at loopBase + k. */
        var loops = 0

        /** Each open local's type; local k is read at localBase + k. */
        val locals = mutableListOf<String>()

        fun node(
            node: JsonElement,
            depth: Int,
        ): Pair<String, Term> {
            count += 1
            require(depth <= contract.depth && count <= nodes) {
                "Program exceeds its limits"
            }
            require(node is JsonObject && node.isNotEmpty()) { "A program node is an object" }
            if (node.size == 1) {
                val (key, literal) = node.entries.single()
                return leaf(key, literal as? JsonPrimitive)
            }
            val op = (node["op"] as? JsonPrimitive)?.content
            val args = node["args"] as? JsonArray
            val signatures = contract.signatures[op] ?: ops.signatures[op]
            require(
                node.keys == setOf("op", "args") &&
                    signatures != null &&
                    args != null &&
                    args.size == signatures.keys.first().size,
            ) { "Unknown program op $op" }
            val given = args.map { node(it, depth + 1) }
            val types = given.map { it.first }
            val result = signatures[types] ?: error("Program op $op does not take $types")
            val terms = given.map { it.second }
            val meaning =
                if (op in
                    contract.signatures
                ) {
                    term(checkNotNull(op), types[0], terms)
                } else {
                    ops.term(op!!, terms, params.size)
                }
            return result to meaning
        }

        private fun leaf(
            key: String,
            literal: JsonPrimitive?,
        ): Pair<String, Term> {
            require(literal != null && !literal.isString) { "Unknown program leaf $key" }
            // Python's int and float stay apart on the wire: 2 is an integer, 2.0 a number.
            val whole = literal.content.none { it == '.' || it == 'e' || it == 'E' }
            val integer = literal.longOrNull?.takeIf { whole }
            val leaf =
                when (key) {
                    "boolean" -> literal.booleanOrNull?.let { value -> BOOLEAN to Term { value } }
                    "integer" -> integer?.let { value -> INTEGER to Term { value } }
                    "number" ->
                        literal.doubleOrNull
                            ?.takeIf { it.isFinite() }
                            ?.let { value -> NUMBER to Term { value } }
                    "arg", "loop", "local" -> integer?.let { slot(key, it) }
                    else -> null
                }
            return leaf ?: error("Unknown program leaf $key")
        }

        /**
         * An argument, a loop's index or a local, read from the frame: arguments first, loop
         * indices from [loopBase], locals from [localBase].
         */
        private fun slot(
            key: String,
            at: Long,
        ): Pair<String, Term>? {
            val (types, base) =
                when (key) {
                    "arg" -> params to 0
                    "loop" -> List(loops) { INTEGER } to loopBase
                    else -> locals to localBase
                }
            val index = base + at.toInt()
            return if (at in 0L until types.size) types[at.toInt()] to Term { it[index] } else null
        }
    }

    /** What [op] means; the catalog's table has already typed its arguments. */
    private fun term(
        op: String,
        type: String,
        terms: List<Term>,
    ): Term {
        val a = terms[0]
        val b = terms.getOrElse(1) { a }
        return when (op) {
            "plus", "minus", "times" -> arithmetic(op, type == INTEGER, a, b)
            "neg" -> negate(type == INTEGER, a)
            "div" -> Term { (a.eval(it) as Double) / (b.eval(it) as Double) }
            "floorDiv", "mod" -> divide(op, a, b)
            "toNumber" -> Term { (a.eval(it) as Long).toDouble() }
            "sin" -> Term { kotlin.math.sin(a.eval(it) as Double) }
            "cos" -> Term { kotlin.math.cos(a.eval(it) as Double) }
            "lt", "le", "gt", "ge" -> compare(op, type == INTEGER, a, b)
            "eq", "ne" -> equal(op == "eq", type, a, b)
            "and", "or", "not" -> logic(op, a, b)
            "if" -> {
                val (test, then, otherwise) = terms
                Term { if (test.eval(it) as Boolean) then.eval(it) else otherwise.eval(it) }
            }
            else -> error("Program op $op has no meaning on this host")
        }
    }

    private fun arithmetic(
        op: String,
        integer: Boolean,
        a: Term,
        b: Term,
    ): Term =
        if (integer) {
            when (op) {
                "plus" -> Term { (a.eval(it) as Long) + (b.eval(it) as Long) }
                "minus" -> Term { (a.eval(it) as Long) - (b.eval(it) as Long) }
                else -> Term { (a.eval(it) as Long) * (b.eval(it) as Long) }
            }
        } else {
            when (op) {
                "plus" -> Term { (a.eval(it) as Double) + (b.eval(it) as Double) }
                "minus" -> Term { (a.eval(it) as Double) - (b.eval(it) as Double) }
                else -> Term { (a.eval(it) as Double) * (b.eval(it) as Double) }
            }
        }

    private fun negate(
        integer: Boolean,
        a: Term,
    ): Term = if (integer) Term { -(a.eval(it) as Long) } else Term { -(a.eval(it) as Double) }

    // Total: a zero divisor gives 0 rather than throwing on the main thread.
    private fun divide(
        op: String,
        a: Term,
        b: Term,
    ): Term =
        Term {
            val divisor = b.eval(it) as Long
            val dividend = a.eval(it) as Long
            when {
                divisor == 0L -> 0L
                op == "floorDiv" -> Math.floorDiv(dividend, divisor)
                else -> Math.floorMod(dividend, divisor)
            }
        }

    private fun compare(
        op: String,
        integer: Boolean,
        a: Term,
        b: Term,
    ): Term {
        val test: (Int) -> Boolean =
            when (op) {
                "lt" -> { order -> order < 0 }
                "le" -> { order -> order <= 0 }
                "gt" -> { order -> order > 0 }
                else -> { order -> order >= 0 }
            }
        // Primitive comparisons, so NaN compares false as in Python.
        return if (integer) {
            Term { test((a.eval(it) as Long).compareTo(b.eval(it) as Long)) }
        } else {
            Term {
                val left = a.eval(it) as Double
                val right = b.eval(it) as Double
                when (op) {
                    "lt" -> left < right
                    "le" -> left <= right
                    "gt" -> left > right
                    else -> left >= right
                }
            }
        }
    }

    private fun equal(
        wanted: Boolean,
        type: String,
        a: Term,
        b: Term,
    ): Term =
        if (type == NUMBER) {
            Term { ((a.eval(it) as Double) == (b.eval(it) as Double)) == wanted }
        } else {
            Term { (a.eval(it) == b.eval(it)) == wanted }
        }

    private fun logic(
        op: String,
        a: Term,
        b: Term,
    ): Term =
        when (op) {
            "and" -> Term { (a.eval(it) as Boolean) && (b.eval(it) as Boolean) }
            "or" -> Term { (a.eval(it) as Boolean) || (b.eval(it) as Boolean) }
            else -> Term { !(a.eval(it) as Boolean) }
        }
}

private const val INTEGER = "integer"
private const val NUMBER = "number"
private const val BOOLEAN = "boolean"
