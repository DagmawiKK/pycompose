package com.pycompose.ir

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.jsonPrimitive
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.DynamicTest
import org.junit.jupiter.api.TestFactory

/**
 * The host judges every corpus document exactly as Python's validator did (`tools/corpus.py`).
 *
 * Two validators generated from one schema can still drift at the edges; the corpus is
 * one valid snapshot and its mutations, with Python's verdict recorded beside each.
 */
class CorpusTest {
    private fun read(name: String): String =
        checkNotNull(
            javaClass.getResource("/corpus/$name"),
        ) { "Missing corpus file $name" }.readText()

    @TestFactory
    fun `the host agrees with Python on every corpus document`(): List<DynamicTest> {
        val verdicts = Json.parseToJsonElement(read("verdicts.json")) as JsonObject
        return verdicts.map { (name, verdict) ->
            DynamicTest.dynamicTest(name) {
                val accepted = IrParser().parse(read("$name.json")).isSuccess
                assertEquals(verdict.jsonPrimitive.boolean, accepted, "verdict for $name")
            }
        }
    }
}
