package com.pycompose.renderer

import androidx.compose.foundation.text.BasicText
import androidx.compose.material3.Button
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import com.pycompose.ir.IrParser
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
            {"version":"0.1.0","schemaVersion":"1.16.0","metadata":{"actionBindings":{
              "app.demo.press.1":{"handlerId":"demo.press","payload":{
                "pressed":{"required":true,"type":"boolean"},
                "held":{"required":true,"type":"boolean"}},"bound":{}}}},
             "root":{"id":"root","type":"Button","props":{
               "text":"Tap","onClick":"increment","onPress":"app.demo.press.1"}}}
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
}
