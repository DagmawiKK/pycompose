package com.pycompose.renderer

import androidx.compose.foundation.text.BasicText
import androidx.compose.material3.Button
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import com.pycompose.ir.AppBinding
import com.pycompose.ir.IrParser
import com.pycompose.ir.PropertyRule
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import com.pycompose.ir.generated.Button as ButtonNode

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class InteractionTest {
    @get:Rule val compose = createComposeRule()

    @Test
    fun anAmbiguousPayloadIsReportedRatherThanGuessed() {
        // The app owns its payload field names; the host fills the one boolean
        // the binding declares as an event field. Two candidates would mean the
        // host picked a field the app did not mean, so it reports instead of
        // dispatching into a guess.
        val source =
            """
            {"version":"0.1.0","schemaVersion":"1.16.0",
              "metadata":{"intents":{"demo.press":{"payload":{
                "pressed":{"required":true,"type":"boolean"},
                "held":{"required":true,"type":"boolean"}}}}},
             "root":{"id":"root","type":"Button","props":{
               "text":"Tap","onClick":"increment","onPress":{"fields":{},"intent":"demo.press"}}}}
            """.trimIndent()
        val snapshot = IrParser().parse(source).getOrThrow()
        val actions = mutableListOf<Action>()
        val reports = mutableListOf<String>()
        val registry =
            ComponentRegistry
                .Builder()
                .register("Button") { node, modifier, context ->
                    val model = node as ButtonNode
                    Button(
                        onClick = {},
                        modifier = modifier,
                        interactionSource =
                            context.interactionSource(
                                model.id,
                                mapOf("press" to model.props.onPress),
                            ),
                    ) {
                        BasicText(model.props.text)
                    }
                }.build()
        val renderer =
            Renderer(registry, ActionDispatcher { actions.add(it) }, report = reports::add)
        compose.setContent { renderer.Render(snapshot) }

        compose.onNodeWithText("Tap").performClick()
        compose.waitUntil(5000) { reports.size == 2 }
        assertTrue(reports.all { it.contains("2 boolean fields") })
        assertTrue(actions.isEmpty())
    }

    @Test
    fun aSettledNumberReachesTheSingleFieldItsTypeFits() {
        // The rail's settled values ride the same sink as a boolean: a float
        // needs a number field, an integer satisfies either numeric
        // declaration, and the app's own field names are the ones filled.
        val actions = mutableListOf<Action>()
        val reports = mutableListOf<String>()
        val bindings =
            mapOf(
                "app.demo.value.1" to
                    AppBinding(
                        payload = mapOf("progress" to PropertyRule("number", required = true)),
                        bound = JsonObject(emptyMap()),
                    ),
                "app.demo.index.1" to
                    AppBinding(
                        payload =
                            mapOf("firstVisibleIndex" to PropertyRule("integer", required = true)),
                        bound = JsonObject(emptyMap()),
                    ),
            )
        val sink = ObservationSink({ bindings }, ActionDispatcher { actions.add(it) }, reports::add)

        sink.observe("value", "app.demo.value.1", JsonPrimitive(0.5f))
        sink.observe("firstVisibleIndex", "app.demo.index.1", JsonPrimitive(3))

        assertTrue(reports.isEmpty())
        assertEquals("app.demo.value.1", actions[0].actionId)
        assertEquals(JsonPrimitive(0.5f), actions[0].payload["progress"])
        assertEquals("app.demo.index.1", actions[1].actionId)
        assertEquals(JsonPrimitive(3), actions[1].payload["firstVisibleIndex"])
    }

    @Test
    fun eachReportToAnActionTakesTheNextSequenceNumber() {
        val actions = mutableListOf<Action>()
        val binding =
            AppBinding(
                payload = mapOf("open" to PropertyRule("boolean", required = true)),
                bound = JsonObject(emptyMap()),
            )
        val reports = Reports()
        val sink =
            ObservationSink(
                { mapOf("app.demo.a.1" to binding, "app.demo.b.1" to binding) },
                ActionDispatcher { actions.add(it) },
                {},
                reports,
            )

        sink.observe("open", "app.demo.a.1", JsonPrimitive(true))
        sink.observe("open", "app.demo.a.1", JsonPrimitive(false))
        sink.observe("open", "app.demo.b.1", JsonPrimitive(true))

        assertEquals(listOf(1L, 2L, 1L), actions.map { it.seq })
        assertTrue(reports.answered("app.demo.a.1", mapOf("app.demo.a.1" to 2L)))
        assertTrue(!reports.answered("app.demo.a.1", mapOf("app.demo.a.1" to 1L)))
    }

    @Test
    fun anAmbiguousNumericPayloadIsReportedRatherThanGuessed() {
        // A number and an integer are two candidates for one integer, and a pick
        // would be a guess: the sink reports and dispatches nothing.
        val actions = mutableListOf<Action>()
        val reports = mutableListOf<String>()
        val bindings =
            mapOf(
                "app.demo.value.1" to
                    AppBinding(
                        payload =
                            mapOf(
                                "from" to PropertyRule("number", required = true),
                                "to" to PropertyRule("integer", required = true),
                            ),
                        bound = JsonObject(emptyMap()),
                    ),
            )
        val sink = ObservationSink({ bindings }, ActionDispatcher { actions.add(it) }, reports::add)

        sink.observe("value", "app.demo.value.1", JsonPrimitive(3))

        assertTrue(actions.isEmpty())
        assertTrue(reports.single().contains("2 integer/number fields"))
    }

    @Test
    fun aFractionCannotFillAnIntegerField() {
        val actions = mutableListOf<Action>()
        val reports = mutableListOf<String>()
        val binding =
            AppBinding(
                payload = mapOf("index" to PropertyRule("integer", required = true)),
                bound = JsonObject(emptyMap()),
            )
        val sink =
            ObservationSink(
                { mapOf("app.demo.index.1" to binding) },
                ActionDispatcher { actions.add(it) },
                reports::add,
            )

        sink.observe("value", "app.demo.index.1", JsonPrimitive(0.5f))

        assertTrue(actions.isEmpty())
        assertTrue(reports.single().contains("0 number fields"))
    }
}
