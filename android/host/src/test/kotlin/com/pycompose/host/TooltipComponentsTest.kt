package com.pycompose.host

import androidx.activity.ComponentActivity
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.longClick
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performTouchInput
import com.pycompose.host.ui.BuiltinComponents
import com.pycompose.host.ui.PyComposeTheme
import com.pycompose.ir.IrParser
import com.pycompose.ir.ValidatedIr
import com.pycompose.renderer.Action
import com.pycompose.renderer.ActionDispatcher
import com.pycompose.renderer.Renderer
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/**
 * The tooltip trio: a scoped plain tooltip, a rich tooltip with title and
 * action slots, the host-owned visibility holder, and the long-press gesture
 * that reports through it.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34], application = android.app.Application::class)
class TooltipComponentsTest {
    @get:Rule val compose = createAndroidComposeRule<ComponentActivity>()

    private fun parse(source: String): ValidatedIr = IrParser().parse(source).getOrThrow()

    private fun renderer(actions: MutableList<Action>): Renderer =
        Renderer(BuiltinComponents.registry(), ActionDispatcher { actions.add(it) })

    @Test
    fun initiallyVisibleTooltipSurvivesAnchorFocusInitialization() {
        val source =
            """
            {"version":"0.1.0","schemaVersion":"1.23.0","root":{
              "id":"tip","type":"TooltipBox","props":{"visible":true,"isPersistent":true},"children":[
                {"id":"anchor","type":"Text","props":{"text":"Initial anchor"}},
                {"id":"tooltip","type":"PlainTooltip","props":{},"slot":"tooltip","children":[
                  {"id":"body","type":"Text","props":{"text":"Initially visible"}}]}]}}
            """.trimIndent()
        val actions = mutableListOf<Action>()
        compose.setContent { PyComposeTheme { renderer(actions).Render(parse(source)) } }

        compose.onNodeWithText("Initially visible").assertExists()
    }

    @Test
    fun richTooltipComposesItsScopedTitleActionAndBody() {
        val source =
            """
            {"version":"0.1.0","schemaVersion":"1.23.0","root":{
              "id":"root","type":"Column","props":{},"children":[
                {"id":"rich","type":"TooltipBox","props":{
                  "visible":true,"isPersistent":true,"hasAction":true,"position":"below"},"children":[
                  {"id":"rich.anchor","type":"Text","props":{"text":"Rich anchor"}},
                  {"id":"rich.tooltip","type":"RichTooltip","props":{"showCaret":true,"maxWidth":280},"slot":"tooltip","children":[
                    {"id":"rich.title","type":"Text","props":{"text":"Rich title"},"slot":"title"},
                    {"id":"rich.action","type":"Text","props":{"text":"Rich action"},"slot":"action"},
                    {"id":"rich.text","type":"Text","props":{"text":"Rich body"}}]}]}]}}
            """.trimIndent()
        val actions = mutableListOf<Action>()
        compose.setContent { PyComposeTheme { renderer(actions).Render(parse(source)) } }

        compose.onNodeWithText("Rich anchor").assertExists()
        compose.onNodeWithText("Rich title").assertExists()
        compose.onNodeWithText("Rich action").assertExists()
        compose.onNodeWithText("Rich body").assertExists()
    }

    @Test
    fun anInvisibleTooltipLeavesOnlyItsAnchorComposed() {
        val source =
            """
            {"version":"0.1.0","schemaVersion":"1.23.0","root":{
              "id":"root","type":"Column","props":{},"children":[
                {"id":"plain","type":"TooltipBox","props":{"visible":false},"children":[
                  {"id":"plain.anchor","type":"Text","props":{"text":"Hidden anchor"}},
                  {"id":"plain.tooltip","type":"PlainTooltip","props":{},"slot":"tooltip","children":[
                    {"id":"plain.text","type":"Text","props":{"text":"Hidden tooltip text"}}]}]}]}}
            """.trimIndent()
        val actions = mutableListOf<Action>()
        compose.setContent { PyComposeTheme { renderer(actions).Render(parse(source)) } }

        compose.onNodeWithText("Hidden anchor").assertExists()
        compose.onNodeWithText("Hidden tooltip text").assertDoesNotExist()
    }

    @Test
    fun aLongPressShowsTheTooltipAndReportsVisibility() {
        val source =
            """
            {"version":"0.1.0","schemaVersion":"1.23.0",
             "metadata":{"actionBindings":{
               "app.demo.visibility":{"handlerId":"demo.visibility","payload":{
                 "visible":{"required":true,"type":"boolean"}},"bound":{}}}},
             "root":{"id":"root","type":"Column","props":{},"children":[
               {"id":"plain","type":"TooltipBox","props":{
                 "enableUserInput":true,
                 "onVisibilityChange":"app.demo.visibility"},"children":[
                 {"id":"plain.anchor","type":"Text","props":{"text":"Gesture anchor"}},
                 {"id":"plain.tooltip","type":"PlainTooltip","props":{},"slot":"tooltip","children":[
                   {"id":"plain.text","type":"Text","props":{"text":"Gesture tooltip text"}}]}]}]}}
            """.trimIndent()
        val actions = mutableListOf<Action>()
        compose.setContent { PyComposeTheme { renderer(actions).Render(parse(source)) } }

        compose.onNodeWithText("Gesture anchor").performTouchInput { longClick() }
        compose.waitUntil(5000) {
            actions.any {
                it.actionId == "app.demo.visibility" &&
                    it.payload.toString() == """{"visible":true}"""
            }
        }
        assertTrue(actions.any { it.actionId == "app.demo.visibility" })
    }
}
