package com.pycompose.ir

import com.pycompose.program.Functions
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.double
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Test

/** Each program Python compiled gives, on the host, the answer its Python gave. */
class FunctionsGoldenTest {
    private val cases =
        Json
            .parseToJsonElement(
                checkNotNull(javaClass.getResource("/programs/functions.json")).readText(),
            ).jsonArray

    @Test
    fun `the host answers every golden call as Python did`() {
        assertEquals(4, cases.size)
        cases.forEach { case ->
            val name =
                case.jsonObject
                    .getValue("name")
                    .jsonPrimitive.content
            val function = Functions.read(case.jsonObject.getValue("program").jsonObject, FUNCTIONS)
            case.jsonObject.getValue("calls").jsonArray.forEach { call ->
                val args =
                    call.jsonObject
                        .getValue("args")
                        .jsonArray
                        .zip(function.signature.params) { arg, type -> value(arg, type) }
                val wanted = value(call.jsonObject.getValue("result"), function.signature.result)
                assertEquals(wanted, function.call(*args.toTypedArray()), "$name$args")
            }
        }
    }

    // Python writes 0 for a float result that is whole; the signature says it is a number.
    private fun value(
        json: JsonElement,
        type: String,
    ): Any {
        val primitive = json as JsonPrimitive
        return when (type) {
            "boolean" -> checkNotNull(primitive.booleanOrNull)
            "integer" -> primitive.long
            else -> primitive.double
        }
    }
}
