package com.pycompose.ir

import com.pycompose.program.BoundLayout
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.double
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Test

/** Each layout program Python compiled places, on the host, the children its Python placed. */
class LayoutsGoldenTest {
    private val cases =
        Json
            .parseToJsonElement(
                checkNotNull(javaClass.getResource("/programs/layouts.json")).readText(),
            ).jsonArray

    @Test
    fun `the host places every golden frame as Python did`() {
        assertEquals(2, cases.size)
        cases.forEach { case ->
            val layout =
                BoundLayout.read(
                    case.jsonObject.getValue("program").jsonObject,
                    FUNCTIONS,
                    LAYOUTS,
                )
            case.jsonObject.getValue("frames").jsonArray.forEach { entry ->
                val frame = entry.jsonObject
                val (maxWidth, maxHeight) =
                    frame
                        .getValue(
                            "max",
                        ).jsonArray
                        .map { it.jsonPrimitive.double }
                val sizes =
                    frame
                        .getValue("sizes")
                        .jsonArray
                        .flatMap { size -> size.jsonArray.map { it.jsonPrimitive.double } }
                        .toDoubleArray()
                val placements = layout.measure(maxWidth, maxHeight, sizes)
                val size = frame.getValue("size").jsonArray.map { it.jsonPrimitive.double }
                assertEquals(size, listOf(placements.width, placements.height))
                val wanted = frame.getValue("placements").jsonArray.map { it.jsonArray }
                assertEquals(wanted.size, placements.placed.count { it })
                wanted.forEach { placed ->
                    val index = placed[0].jsonPrimitive.long.toInt()
                    assertEquals(
                        listOf(placed[1].jsonPrimitive.double, placed[2].jsonPrimitive.double),
                        listOf(placements.x[index], placements.y[index]),
                    )
                }
            }
        }
    }
}
