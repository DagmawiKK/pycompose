package com.pycompose.ir

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNotNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import org.junit.jupiter.params.ParameterizedTest
import org.junit.jupiter.params.provider.ValueSource

class IrParserTest {
    @Test
    fun `valid metadata preserves Unicode and keys in distinct objects`() {
        val source = """{"version":"0.1.0","schemaVersion":"1.0.0",
            "root":{"id":"root","type":"Text","props":{"text":"ok"}},
            "metadata":{"nested":[{"key":1},{"key":2}],"emoji":"\ud83d\ude00"}}
        """
        val snapshot = IrParser().parse(source).getOrThrow().snapshot
        assertEquals("\"😀\"", snapshot.metadata?.get("emoji").toString())
    }

    @Test
    fun `legacy modifier objects remain data compatible with Python`() {
        val source = """{"version":"0.1.0","schemaVersion":"1.0.0",
            "root":{"id":"root","type":"Text","props":{
                "text":"ok","modifier":{"padding":8}}}}
        """
        val parsed = IrParser().parse(source).getOrThrow()
        assertEquals(
            "8",
            parsed.snapshot.root.props.modifier
                ?.get("padding")
                .toString(),
        )
    }

    @Test
    fun `Python golden parses through the public contract`() {
        val source = checkNotNull(javaClass.getResource("/ir_counter.json")).readText()
        val parsed = IrParser().parse(source).getOrThrow()
        assertEquals("1.0.0", parsed.snapshot.schemaVersion)
        assertEquals("root", parsed.snapshot.root.id)
        assertNotNull(parsed.snapshot.root)
    }

    @Test
    fun `a declared slot survives parsing into the model`() {
        // The wire carries the slot, the contract checks it, and the renderer
        // reads it off the model -- so it has to be a model property, not just a
        // validated field.
        val source =
            """
            {"version":"0.1.0","schemaVersion":"1.15.0","root":{
            "id":"root","type":"Scaffold","props":{},"children":[
              {"id":"bar","type":"Text","props":{"text":"Top bar"},"slot":"topBar"}]}}
            """.trimIndent()
        val parsed = IrParser().parse(source).getOrThrow().snapshot
        assertEquals(
            "topBar",
            parsed.root.children
                .single()
                .slot,
        )
    }

    @Test
    fun `all component golden parses including ordered modifiers and typed props`() {
        val source = checkNotNull(javaClass.getResource("/component_screen.json")).readText()
        val parsed = IrParser().parse(source).getOrThrow()
        assertEquals("Scaffold", parsed.snapshot.root.componentType)
        assertEquals(1, parsed.snapshot.root.children.size)
    }

    @ParameterizedTest
    @ValueSource(
        strings = [
            """{"id":"root","type":"Unknown","props":{}}""",
            """{"id":"root","type":"Text","props":{"text":"ok","extra":1}}""",
            """{"id":"root","type":"Text","props":{"text":"ok","style":"bad"}}""",
            """{"id":"root","type":"Text","props":{"text":"ok"},"children":[]}""",
            """{"id":"root","type":"Text","props":{"text":"ok"},"extra":1}""",
            """{"id":"root","type":"Text","props":{"text":null}}""",
            """{"id":"root","type":"Text","props":{"text":"ok","color":null}}""",
            """{"id":"root","type":"Text","props":{"text":"ok","modifier":null}}""",
            """{"id":"root","type":"Button","props":{"text":"ok","onClick":"bad"}}""",
            """{"id":"root","type":"Button",
                "props":{"text":"ok","onClick":"increment","enabled":"true"}}""",
            """{"id":"root","type":"Spacer","props":{"modifier":{
                "operations":[{"type":"padding","value":-1}]}}}""",
            """{"id":"root","type":"Spacer","props":{"modifier":{
                "operations":[{"type":"fillMaxWidth","fraction":2}]}}}""",
            """{"id":"root","type":"Spacer","props":{"modifier":{
                "operations":[{"type":"padding","value":"1"}]}}}""",
            """{"id":"root","type":"Spacer","props":{"modifier":{
                "operations":[{"type":"missing"}]}}}""",
            """{"id":"","type":"Text","props":{"text":"ok"}}""",
            """{"id":"root","type":"Column","props":{},"children":[
                {"id":"same","type":"Text","props":{"text":"a"}},
                {"id":"same","type":"Text","props":{"text":"b"}}]}""",
            // The root has no parent, so it fills no slot.
            """{"id":"root","type":"Text","props":{"text":"ok"},"slot":"topBar"}""",
            // Column declares no slots, so the child has nowhere to compose.
            """{"id":"root","type":"Column","props":{},"children":[
                {"id":"child","type":"Text","props":{"text":"a"},"slot":"topBar"}]}""",
        ],
    )
    fun `wire failures return diagnostics rather than partially valid models`(node: String) {
        val source = """{"version":"0.1.0","schemaVersion":"1.0.0","root":$node}"""
        val result = IrParser().parse(source)
        assertTrue(result.isFailure, node)
        assertTrue(!result.exceptionOrNull()?.message.isNullOrBlank())
    }

    @Test
    fun `a value prop is refused in its legacy string form`() {
        // A value prop names a family; a bare string names none, so there is
        // nothing to resolve it against and the report must say so.
        val source = """{"version":"0.1.0","schemaVersion":"1.22.0",
            "root":{"id":"root","type":"Card","props":{
                "onClick":"increment","shape":"rounded"}}}"""
        val result = IrParser().parse(source)
        assertTrue(result.isFailure)
        assertTrue(
            result
                .exceptionOrNull()
                ?.message
                .orEmpty()
                .contains("tagged value object"),
        )
    }

    @Test
    fun `version gates compare numeric versions and accept a compatible library`() {
        val source = checkNotNull(javaClass.getResource("/ir_counter.json")).readText()
        assertTrue(IrParser("0.9.0").parse(source).isSuccess)
        assertTrue(IrParser("1.0.1").parse(source).isFailure)
        assertTrue(IrParser().parse(source.replace("0.1.0", "0.10.0")).isSuccess)
        assertTrue(IrParser().parse(source.replace("0.1.0", "0.0.9")).isFailure)
        assertTrue(IrParser().parse(source.replace("1.0.0", "2.0.0")).isFailure)
        assertTrue(IrParser().parse(source.replace("1.0.0", "01.0.0")).isFailure)
    }

    @ParameterizedTest
    @ValueSource(
        strings = [
            """{"number":NaN}""",
            """{"number":1e999}""",
            """{"text":"\ud800"}""",
            """{"repeated":1,"\u0072epeated":2}""",
            """null""",
        ],
    )
    fun `ambiguous and non canonical metadata fails closed`(metadata: String) {
        val node = """{"id":"root","type":"Text","props":{"text":"ok"}}"""
        val source = """{"version":"0.1.0","schemaVersion":"1.0.0",
            "root":$node,"metadata":$metadata}"""
        assertTrue(IrParser().parse(source).isFailure, metadata)
    }
}
