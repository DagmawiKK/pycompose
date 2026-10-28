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
            {"at":[1],"id":"root.count","op":"setProp","prop":"text","value":"2"}],
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
    fun `an op whose indices reach a different node fails and asks for a whole one next`() {
        val stream = SnapshotStream()
        stream.accept(full("0", serial = 1)).getOrThrow()

        assertTrue(stream.accept(patch.replace("\"at\":[1]", "\"at\":[0]")).isFailure)
        assertEquals(SnapshotStream.NONE, stream.serial)
    }

    @Test
    fun `ids that name no path still patch, since indices locate the node`() {
        fun compact(count: String) =
            """{"root":{"id":"0","type":"Column","props":{},"children":[
                {"id":"1","type":"Text","props":{"text":"Counter"}},
                {"id":"2","type":"Text","props":{"text":"$count"}}]},
                "schemaVersion":"1.0.0","version":"0.1.0"}"""
        val stream = SnapshotStream()
        stream
            .accept(
                compact("0").replace("{\"root\"", "{\"kind\":\"full\",\"serial\":1,\"root\""),
            ).getOrThrow()

        val patched = stream.accept(patch.replace("\"root.count\"", "\"2\"")).getOrThrow()
        assertEquals(IrParser().parse(compact("2")).getOrThrow().snapshot, patched.snapshot)
    }

    @Test
    fun `an envelope for another surface is refused`() {
        val stream = SnapshotStream()
        val dialog =
            full(
                "0",
                serial = 1,
            ).replace("\"serial\":1", "\"serial\":1,\"surface\":\"dialog\"")

        assertTrue(stream.accept(dialog).isFailure)
        assertTrue(stream.accept(dialog.replace("dialog", "main")).isSuccess)
    }

    @Test
    fun `a patch that keeps app data carries over the data the host holds`() {
        val stream = SnapshotStream()
        stream
            .accept(
                """{"kind":"full","metadata":{"data":{"note":"a"}},"root":${root("0")},
                    "schemaVersion":"1.4.0","serial":1,"version":"0.1.0"}""",
            ).getOrThrow()

        val patched =
            stream
                .accept(
                    patch
                        .replace("\"kind\":\"patch\"", "\"keep\":[\"data\"],\"kind\":\"patch\"")
                        .replace("\"schemaVersion\":\"1.0.0\"", "\"schemaVersion\":\"1.4.0\""),
                ).getOrThrow()
                .snapshot

        assertEquals(
            kotlinx.serialization.json.JsonObject(
                mapOf(
                    "note" to kotlinx.serialization.json.JsonPrimitive("a"),
                ),
            ),
            patched.metadata?.get("data"),
        )
    }

    @Test
    fun `a bare snapshot is whole and holds no serial`() {
        val stream = SnapshotStream()
        assertTrue(stream.accept(bare("0")).isSuccess)
        assertEquals(SnapshotStream.NONE, stream.serial)
    }

    @Test
    fun `a patch states its intent contracts whole`() {
        val contract = """{"payload":{}}"""
        val stream = SnapshotStream()
        stream
            .accept(
                """{"kind":"full","metadata":{"intents":{"demo.a":$contract}},
                    "root":${root("0")},"schemaVersion":"1.2.0","serial":1,"version":"0.1.0"}""",
            ).getOrThrow()
        val patched =
            stream
                .accept(
                    """{"baseSerial":1,"kind":"patch",
                        "metadata":{"intents":{"demo.b":$contract}},
                        "ops":[],"schemaVersion":"1.2.0","serial":2,"version":"0.1.0"}""",
                ).getOrThrow()
                .snapshot

        val intents = patched.metadata?.get("intents") as kotlinx.serialization.json.JsonObject
        assertEquals(setOf("demo.b"), intents.keys)
    }
}
