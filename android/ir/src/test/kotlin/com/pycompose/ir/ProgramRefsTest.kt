package com.pycompose.ir

import com.pycompose.ir.generated.CanvasWithoutContentDescription
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertSame
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

/** The envelopes Python wrote: programs cross once and props name them by content. */
class ProgramRefsTest {
    private val envelopes =
        Json
            .parseToJsonElement(
                checkNotNull(javaClass.getResource("/programs/refs.json")).readText(),
            ).jsonObject

    private fun envelope(kind: String) = envelopes.getValue(kind).toString()

    private fun drawing(
        snapshot: ValidatedIr,
        row: Int,
    ): JsonObject =
        (snapshot.snapshot.root.children[row] as CanvasWithoutContentDescription).props.onDraw

    @Test
    fun `each row reads the one program in place, and a patch keeps it`() {
        val stream = SnapshotStream()
        val full = stream.accept(envelope("full")).getOrThrow()
        val first = drawing(full, 0).getValue("program")
        assertTrue("body" in first.jsonObject)
        assertSame(first, drawing(full, 1).getValue("program"))

        val patched = stream.accept(envelope("patch")).getOrThrow()
        assertEquals(
            0.75,
            drawing(patched, 1)
                .getValue("args")
                .jsonArray[0]
                .jsonPrimitive.content
                .toDouble(),
        )
        assertSame(first, drawing(patched, 1).getValue("program"))
        assertSame(full.snapshot.root.children[0], patched.snapshot.root.children[0])
    }

    @Test
    fun `a prop naming a program the snapshot lacks is refused`() {
        val full = envelopes.getValue("full").jsonObject
        val bare = JsonObject(full - "metadata").toString()
        assertTrue(SnapshotStream().accept(bare).isFailure)
    }
}
