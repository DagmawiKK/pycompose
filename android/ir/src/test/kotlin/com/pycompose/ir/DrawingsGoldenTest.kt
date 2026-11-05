package com.pycompose.ir

import com.pycompose.ir.generated.IrContract
import com.pycompose.program.DrawCall
import com.pycompose.program.Drawings
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.double
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import kotlin.math.abs

private const val ULPS = 1e-12

/** Each draw program Python compiled draws, on the host, the frame its Python drew. */
class DrawingsGoldenTest {
    private val cases =
        Json
            .parseToJsonElement(
                checkNotNull(javaClass.getResource("/programs/drawings.json")).readText(),
            ).jsonArray

    @Test
    fun `the host draws every golden frame as Python did`() {
        assertEquals(2, cases.size)
        cases.forEach { case ->
            val drawing =
                Drawings.read(
                    case.jsonObject.getValue("program").jsonObject,
                    FUNCTIONS,
                    DRAWINGS,
                )
            case.jsonObject.getValue("frames").jsonArray.forEach { frame ->
                val size =
                    frame.jsonObject
                        .getValue(
                            "size",
                        ).jsonArray
                        .map { it.jsonPrimitive.double }
                val drawn = mutableListOf<DrawCall>()
                drawing.draw(*size.toTypedArray()) { drawn += it }
                val wanted =
                    frame.jsonObject
                        .getValue("draws")
                        .jsonArray
                        .map { it.jsonArray }
                assertEquals(wanted.map { it[0].jsonPrimitive.content }, drawn.map { it.name })
                wanted.zip(drawn) { draw, call ->
                    val types = checkNotNull(DRAWINGS.calls[call.name])
                    val args =
                        draw[1].jsonArray.zip(
                            types,
                        ) { arg, type -> value(arg as JsonPrimitive, type) }
                    args.zip(call.args) { want, got -> same(want, got, "${call.name} at $size") }
                }
            }
        }
    }

    @Test
    fun `a canvas whose draw program the host could not run is refused before it draws`() {
        val program = cases[0].jsonObject.getValue("program").toString()
        val canvas = "CanvasWithoutContentDescription"

        fun snapshot(onDraw: String) =
            """{"root":{"id":"0","type":"$canvas","props":{"onDraw":$onDraw}},""" +
                """"schemaVersion":"${IrContract.SCHEMA_VERSION}","version":"0.1.0"}"""
        assertTrue(IrParser().parse(snapshot(program)).isSuccess)
        assertTrue(
            IrParser().parse(snapshot(program.replace("\"circle\"", "\"spiral\""))).isFailure,
        )
    }

    // sin and cos are not correctly rounded on either side, so a number may differ in its last bit.
    private fun same(
        wanted: Any,
        got: Any,
        what: String,
    ) = if (wanted is Double && got is Double) {
        assertEquals(wanted, got, abs(wanted) * ULPS + ULPS, what)
    } else {
        assertEquals(wanted, got, what)
    }

    private fun value(
        primitive: JsonPrimitive,
        type: String,
    ): Any =
        when (type) {
            "boolean" -> checkNotNull(primitive.booleanOrNull)
            "integer" -> primitive.long
            else -> primitive.double
        }
}
