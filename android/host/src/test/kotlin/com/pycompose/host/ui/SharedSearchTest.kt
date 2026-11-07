package com.pycompose.host.ui

import androidx.activity.ComponentActivity
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.hasAnyDescendant
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTextInput
import com.pycompose.host.intent
import com.pycompose.ir.IrParser
import com.pycompose.ir.ValidatedIr
import com.pycompose.renderer.Action
import com.pycompose.renderer.ActionDispatcher
import com.pycompose.renderer.Renderer
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** A search from generated parts: the bar owns its state; its field and surface name it. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class SharedSearchTest {
    @get:Rule val compose = createAndroidComposeRule<ComponentActivity>()

    private val actions = mutableListOf<Action>()

    @Test
    fun theSurfaceNamingTheBarOpensWhenTheAppExpandsIt() {
        val ir = mutableStateOf(snapshot(value = "collapsed"))
        render(ir)
        compose.onNode(hasText("A result")).assertDoesNotExist()

        compose.runOnIdle { ir.value = snapshot(value = "expanded") }
        compose.waitForIdle()

        compose.onNode(hasText("A result")).assertExists()
    }

    @Test
    fun focusingTheFieldExpandsTheSharedBarAndReportsItOnce() {
        val ir = mutableStateOf(snapshot(value = null))
        render(ir)

        compose.onNode(field("C"), useUnmergedTree = true).performClick()
        compose.waitForIdle()

        val expansions = actions.filter { it.actionId == intent("demo.expand") }
        assertEquals(listOf(JsonPrimitive("expanded")), expansions.map { it.payload["value"] })
    }

    @Test
    fun typingInTheFieldReportsTheEdit() {
        val ir = mutableStateOf(snapshot(value = null))
        render(ir)

        compose.onNode(field("C"), useUnmergedTree = true).performTextInput("!")
        compose.waitForIdle()

        val edits = actions.filter { it.actionId == intent("demo.edit") }
        assertTrue(edits.isNotEmpty())
        assertEquals(JsonPrimitive("compose!"), edits.last().payload["text"])
    }

    @Test
    fun aSurfaceNamingNoComposedBarWaitsInsteadOfCrashing() {
        val ir = mutableStateOf(snapshot(value = "expanded", owner = "missing"))
        render(ir)

        compose.onNode(hasText("A result")).assertDoesNotExist()
    }

    private fun render(ir: androidx.compose.runtime.State<ValidatedIr>) {
        val renderer = Renderer(BuiltinComponents.registry(), ActionDispatcher { actions.add(it) })
        compose.setContent { PyComposeTheme { renderer.Render(ir.value) } }
        compose.waitForIdle()
    }

    private fun field(marker: String) = hasSetTextAction() and hasAnyDescendant(hasText(marker))

    private fun input(
        id: String,
        owner: String,
        icon: String,
    ): String =
        """{"id":"$id","type":"SearchBarStateInputField","slot":"inputField","props":{
             "searchBarState":"$owner","text":"compose","selectionStart":7,"selectionEnd":7,
             "onEdit":{"fields":{},"intent":"demo.edit"},
             "onSearch":{"fields":{},"intent":"demo.search"}},"children":[
             {"id":"$id.icon","type":"Text","slot":"leadingIcon","props":{"text":"$icon"}}]}"""

    private fun snapshot(
        value: String?,
        owner: String = "bar",
    ): ValidatedIr {
        val stated = value?.let { "\"value\":\"$it\"," } ?: ""
        return IrParser()
            .parse(
                """
                {"version":"0.1.0","schemaVersion":"1.23.0",
                  "metadata":{"intents":{"demo.edit":{"payload":{
                    "text":{"type":"string","required":true},
                    "selectionStart":{"type":"integer","required":true},
                    "selectionEnd":{"type":"integer","required":true}}},"demo.search":{"payload":{
                    "query":{"type":"string","required":true}}},"demo.expand":{"payload":{
                    "value":{"type":"string","required":true}}}}},
                 "root":{"id":"page","type":"Column","props":{},"children":[
                   {"id":"bar","type":"StatefulSearchBar","props":{$stated
                     "onValueChange":{"fields":{},"intent":"demo.expand"}},"children":[
                     ${input("collapsed", "bar", "C")}]},
                   {"id":"expanded","type":"ExpandedFullScreenSearchBar",
                     "props":{"state":"$owner"},"children":[
                     ${input("expanded.input", owner, "E")},
                     {"id":"result","type":"Text","props":{"text":"A result"}}]}]}}
                """.trimIndent(),
            ).getOrThrow()
    }
}
