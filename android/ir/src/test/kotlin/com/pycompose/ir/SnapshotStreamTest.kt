package com.pycompose.ir

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertSame
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class SnapshotStreamTest {
    private fun root(count: String) =
        """{"id":"root","type":"Column","props":{},"children":[
            {"id":"root.title","type":"Text","props":{"text":"Counter"}},
            {"id":"root.count","type":"Text","props":{"text":"$count"}}]}"""

    private fun full(
        count: String,
        serial: Int,
    ) = """{"kind":"full","root":${root(
        count,
    )},"schemaVersion":"1.0.0","serial":$serial,"version":"0.1.0"}"""

    private fun bare(count: String) =
        """{"root":${root(count)},"schemaVersion":"1.0.0","version":"0.1.0"}"""

    private val patch =
        """{"baseSerial":1,"kind":"patch","ops":[
            {"id":"root.count","op":"setProp","prop":"text","value":"2"}],
            "schemaVersion":"1.0.0","serial":2,"version":"0.1.0"}"""

    @Test
    fun `a patch rebuilds the latest snapshot and shares every unchanged node`() {
        val stream = SnapshotStream()
        val base = stream.accept(full("0", serial = 1)).getOrThrow().snapshot
        val patched = stream.accept(patch).getOrThrow().snapshot

        val whole = IrParser().parse(bare("2")).getOrThrow().snapshot
        assertEquals(whole, patched)
        assertEquals(2L, stream.serial)
        assertSame(base.root.children[0], patched.root.children[0])
    }

    @Test
    fun `a patch against a snapshot not held fails and asks for a whole one next`() {
        val stream = SnapshotStream()
        stream.accept(full("0", serial = 7)).getOrThrow()

        assertTrue(stream.accept(patch).isFailure)
        assertEquals(SnapshotStream.NONE, stream.serial)
    }

    @Test
    fun `a bare snapshot is whole and holds no serial`() {
        val stream = SnapshotStream()
        assertTrue(stream.accept(bare("0")).isSuccess)
        assertEquals(SnapshotStream.NONE, stream.serial)
    }

    @Test
    fun `a bindings delta is applied to the bindings the host holds`() {
        fun contract(handler: String) = """{"handlerId":"$handler","payload":{},"bound":{}}"""
        val stream = SnapshotStream()
        stream
            .accept(
                """{"kind":"full","metadata":{"actionBindings":{
                    "app.demo.a.1":${contract("demo.a")},"app.demo.b.1":${contract("demo.b")}}},
                    "root":${root("0")},"schemaVersion":"1.2.0","serial":1,"version":"0.1.0"}""",
            ).getOrThrow()
        val patched =
            stream
                .accept(
                    """{"baseSerial":1,"bindings":{"remove":["app.demo.a.1"],
                        "set":{"app.demo.c.1":${contract("demo.c")}}},"kind":"patch","ops":[],
                        "schemaVersion":"1.2.0","serial":2,"version":"0.1.0"}""",
                ).getOrThrow()
                .snapshot

        val bindings =
            patched.metadata?.get(
                "actionBindings",
            ) as kotlinx.serialization.json.JsonObject
        assertEquals(setOf("app.demo.b.1", "app.demo.c.1"), bindings.keys)
    }
}
