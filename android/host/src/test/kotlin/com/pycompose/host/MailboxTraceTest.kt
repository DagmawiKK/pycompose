package com.pycompose.host

import androidx.lifecycle.SavedStateHandle
import com.pycompose.host.bridge.BridgeSurface
import com.pycompose.ir.generated.IrContract
import com.pycompose.renderer.Action
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Test
import java.io.File
import kotlin.random.Random

/**
 * Record runs of the host's command queue for trace validation against the protocol model.
 *
 * Each run posts a random mix of settled reports and intents, letting the worker drain at
 * random points, and logs what was posted, what reached Python and when the host pulled.
 * `tools/spec/trace.py` checks every run against `Mailbox.tla`, in which a report collapses
 * into an earlier one only after the last queued intent.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class MailboxTraceTest {
    /** A worker that logs every action it is handed and every pull. */
    private class Recording(
        val events: MutableList<JsonObject>,
    ) : BridgeSurface {
        override fun start(
            route: String,
            restore: String,
        ) = Unit

        override fun acceptAction(action: String) {
            events.add(event("process", Json.parseToJsonElement(action).jsonObject))
        }

        override fun fetchLatestSnapshot(): String {
            events.add(JsonObject(mapOf("event" to JsonPrimitive("pull"))))
            return SNAPSHOT
        }

        override fun fetchLatestError(): String = ""

        override fun reload(
            route: String,
            restore: String,
        ) = true
    }

    @Test fun `every recorded run follows the protocol model`() {
        repeat(RUNS) { seed -> record(seed) }
    }

    private fun record(seed: Int) =
        runTest {
            val events = mutableListOf<JsonObject>()
            val model =
                PyComposeViewModel(
                    Recording(events),
                    SavedStateHandle(),
                    StandardTestDispatcher(testScheduler),
                )
            advanceUntilIdle()
            val random = Random(seed)
            val seqs = mutableMapOf<String, Long>()
            repeat(STEPS) { n -> step(random, n, model, events, seqs) }
            advanceUntilIdle()
            model.close()

            val posted = events.filter { it.text("event") == "post" && it.text("kind") == "intent" }
            val processed =
                events.filter {
                    it.text("event") == "process" &&
                        it.text("kind") == "intent"
                }
            assertEquals(posted.map { it.text("id") }, processed.map { it.text("id") })
            System.getProperty("pycompose.traces")?.let { dir ->
                File(
                    dir,
                ).apply { mkdirs() }
                    .resolve(
                        "host-$seed.json",
                    ).writeText(JsonArray(events).toString())
            }
        }

    private fun TestScope.step(
        random: Random,
        n: Int,
        model: PyComposeViewModel,
        events: MutableList<JsonObject>,
        seqs: MutableMap<String, Long>,
    ) {
        val roll = random.nextInt(100)
        val action =
            when {
                roll < REPORTS -> {
                    val widget = WIDGETS.random(random)
                    val seq = seqs.merge(widget, 1L, Long::plus)
                    Action(
                        widget,
                        JsonObject(mapOf("value" to JsonPrimitive(VALUES.random(random)))),
                        seq = seq,
                    )
                }
                roll < REPORTS + INTENTS -> Action(TAP, JsonObject(mapOf("n" to JsonPrimitive(n))))
                else -> null
            }
        if (action == null) {
            advanceUntilIdle()
        } else {
            events.add(event("post", Json.parseToJsonElement(action.toJson()).jsonObject))
            model.dispatch(action)
        }
    }

    private companion object {
        const val RUNS = 25
        const val STEPS = 40
        const val REPORTS = 45
        const val INTENTS = 20
        const val TAP = "demo.Tap"
        val WIDGETS = listOf("demo.W1", "demo.W2")
        val VALUES = listOf("a", "b")

        val SNAPSHOT =
            """
            {"version":"0.1.0","schemaVersion":"${IrContract.SCHEMA_VERSION}",
             "metadata":{"intents":{
               "demo.W1":{"payload":{"value":{"required":true,"type":"string"}}},
               "demo.W2":{"payload":{"value":{"required":true,"type":"string"}}},
               "demo.Tap":{"payload":{"n":{"required":true,"type":"integer"}}}}},
             "root":{"id":"root","type":"Text","props":{"text":"trace"}}}
            """.trimIndent()

        fun JsonObject.text(key: String) = this[key]?.jsonPrimitive?.content

        /** One envelope as the model names it: a report if it carries a number, else an intent. */
        fun event(
            name: String,
            envelope: JsonObject,
        ): JsonObject {
            val intent = envelope.text("intent").orEmpty()
            val payload = envelope["payload"]?.jsonObject.orEmpty()
            val fields =
                if (envelope["seq"] != null) {
                    mapOf(
                        "kind" to "report",
                        "w" to intent,
                        "v" to payload["value"]?.jsonPrimitive?.content,
                    )
                } else {
                    mapOf("kind" to "intent", "id" to "i${payload["n"]?.jsonPrimitive?.content}")
                }
            return JsonObject((fields + ("event" to name)).mapValues { JsonPrimitive(it.value) })
        }
    }
}
