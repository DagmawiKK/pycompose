package com.pycompose.program

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * What a function prop runs: a value function of the arguments the host gives, and the values
 * bound to the parameters after them.
 *
 * A drawer asks its function whether it may settle at an anchor, giving the anchor's wire
 * spelling; a swipe asks how far is far enough, giving its whole distance.
 *
 * @property function The checked program.
 */
class BoundFunction internal constructor(
    val function: Function,
    private val args: List<Any>,
) {
    /**
     * Call it.
     *
     * @param given The host's arguments, typed as the prop states them.
     * @return The answer, typed as the prop states it.
     */
    fun call(vararg given: Any): Any = function.call(given.asList() + args)

    companion object {
        /**
         * Check what a function prop runs and build it: a function of the host's arguments,
         * or one bound.
         *
         * @param value The prop's wire value, its program in place.
         * @param head The types of the arguments the host gives, in order.
         * @param result The type the host needs back.
         * @param contract The catalog's operations and limits.
         * @return The function with its arguments bound.
         */
        fun read(
            value: JsonObject,
            head: List<String>,
            result: String,
            contract: FunctionContract,
        ): BoundFunction {
            val bound = (value["type"] as? JsonPrimitive)?.content == "bound"
            require(!bound || value.keys == setOf("type", "program", "args")) {
                "A bound program is {type: bound, program, args}"
            }
            val program = if (bound) value["program"] as? JsonObject else value
            val args = if (bound) value["args"] as? JsonArray else JsonArray(emptyList())
            require(program != null && args != null) { "A bound program holds a program and args" }
            val function = Functions.read(program, contract)
            val params = function.signature.params
            require(params.take(head.size) == head && function.signature.result == result) {
                "A function ${function.signature} is not ($head, ...) -> $result"
            }
            val rest = params.drop(head.size)
            require(args.size == rest.size) { "A function needs ${rest.size} bound arguments" }
            return BoundFunction(function, args.zip(rest, Statements::argument))
        }
    }
}
