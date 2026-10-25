package com.pycompose.host

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshots.Snapshot
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performTextInput
import androidx.compose.ui.test.performTextReplacement
import com.pycompose.host.ui.BuiltinComponents
import com.pycompose.host.ui.PyComposeTheme
import com.pycompose.ir.IrParser
import com.pycompose.ir.ValidatedIr
import com.pycompose.renderer.Action
import com.pycompose.renderer.ActionDispatcher
import com.pycompose.renderer.Renderer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/**
 * Round 9 layout and animation entries: flow scopes, horizontal laziness, the
 * animation wrappers, a RowScope app bar, and the standalone search field.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34], application = android.app.Application::class)
class RoundNineComponentsTest {
    @get:Rule val compose = createComposeRule()

    private fun parse(source: String): ValidatedIr = IrParser().parse(source).getOrThrow()

    private fun renderer(actions: MutableList<Action>): Renderer =
        Renderer(BuiltinComponents.registry(), ActionDispatcher { actions.add(it) })

    @Test
    fun flowRowsAndAnimationsComposeTheirChildren() {
        val source =
            """
            {"version":"0.1.0","schemaVersion":"1.23.0","root":{
              "id":"root","type":"Column","props":{},"children":[
                {"id":"flow.row","type":"FlowRow","props":{
                  "maxItemsInEachRow":2,"itemVerticalAlignment":"center"},"children":[
                  {"id":"flow.row.one","type":"Text","props":{"text":"Flow one"}},
                  {"id":"flow.row.two","type":"Text","props":{"text":"Flow two"}}]},
                {"id":"flow.column","type":"FlowColumn","props":{
                  "maxItemsInEachColumn":2,"itemHorizontalAlignment":"end"},"children":[
                  {"id":"flow.column.one","type":"Text","props":{"text":"Flow three"}},
                  {"id":"flow.column.two","type":"Text","props":{"text":"Flow four"}}]},
                {"id":"lazy.row","type":"LazyRow","props":{},"children":[
                  {"id":"lazy.row.one","type":"Text","props":{"text":"Lazy one"}},
                  {"id":"lazy.row.two","type":"Text","props":{"text":"Lazy two"}}]},
                {"id":"visible","type":"AnimatedVisibility","props":{"visible":true},"children":[
                  {"id":"visible.text","type":"Text","props":{"text":"Visible one"}}]},
                {"id":"content","type":"AnimatedContent","props":{"targetState":"one"},"children":[
                  {"id":"content.text","type":"Text","props":{"text":"Animated content"}}]},
                {"id":"crossfade","type":"Crossfade","props":{"targetState":"one"},"children":[
                  {"id":"crossfade.text","type":"Text","props":{"text":"Crossfade content"}}]},
                {"id":"bottom","type":"BottomAppBar","props":{},"children":[
                  {"id":"bottom.text","type":"Text","props":{"text":"Bottom bar"}}]}]}}
            """.trimIndent()
        val actions = mutableListOf<Action>()
        compose.setContent { PyComposeTheme { renderer(actions).Render(parse(source)) } }

        for (text in listOf(
            "Flow one",
            "Flow two",
            "Flow three",
            "Flow four",
            "Lazy one",
            "Lazy two",
        )) {
            compose.onNodeWithText(text).assertExists()
        }
        compose.onNodeWithText("Visible one").assertExists()
        compose.onNodeWithText("Animated content").assertExists()
        compose.onNodeWithText("Crossfade content").assertExists()
        compose.onNodeWithText("Bottom bar").assertExists()
    }

    @Test
    fun anOutgoingKeyKeepsItsOwnSubtreeWhileItAnimatesOut() {
        fun snapshot(key: String) =
            parse(
                """
                {"version":"0.1.0","schemaVersion":"1.23.0","root":{
                  "id":"fade","type":"Crossfade","props":{"targetState":"$key"},"children":[
                    {"id":"fade.$key","type":"Text","props":{"text":"Page $key"}}]}}
                """.trimIndent(),
            )
        var shown by mutableStateOf(snapshot("one"))
        val renderer = renderer(mutableListOf())
        compose.setContent { PyComposeTheme { renderer.Render(shown) } }
        compose.onNodeWithText("Page one").assertExists()

        compose.mainClock.autoAdvance = false
        shown = snapshot("two")
        Snapshot.sendApplyNotifications()
        compose.mainClock.advanceTimeBy(FRAME_MS)
        // Python sent only page two; page one still fades out as itself.
        compose.onNodeWithText("Page one").assertExists()
        compose.onNodeWithText("Page two").assertExists()

        compose.mainClock.autoAdvance = true
        compose.waitForIdle()
        compose.onNodeWithText("Page one").assertDoesNotExist()
        compose.onNodeWithText("Page two").assertExists()
    }

    @Test
    fun theKeyOnScreenTakesItsNewSubtreeAndItsNewBindings() {
        // Found on an emulator: a page kept its first subtree and first bindings,
        // so Python's updates never showed and a later binding was unknown.
        val first =
            parse(
                """
                {"version":"0.1.0","schemaVersion":"1.23.0","root":{
                  "id":"page","type":"AnimatedContent","props":{"targetState":"time"},"children":[
                    {"id":"page.text","type":"Text","props":{"text":"First"}}]}}
                """.trimIndent(),
            )
        val second =
            parse(
                """
                {"version":"0.1.0","schemaVersion":"1.23.0",
                 "metadata":{"actionBindings":{"app.page.note":{"handlerId":"page.note",
                   "payload":{"value":{"required":true,"type":"string"}},"bound":{}}}},
                 "root":{
                  "id":"page","type":"AnimatedContent","props":{"targetState":"time"},"children":[
                    {"id":"page.field","type":"TextField","props":{
                      "value":"","label":"Second","onValueChange":"app.page.note"}}]}}
                """.trimIndent(),
            )
        val actions = mutableListOf<Action>()
        var shown by mutableStateOf(first)
        val renderer = renderer(actions)
        compose.setContent { PyComposeTheme { renderer.Render(shown) } }
        compose.onNodeWithText("First").assertExists()

        shown = second
        compose.waitForIdle()
        compose.onNodeWithText("Second").performTextInput("a")
        compose.waitUntil(5000) { actions.any { it.actionId == "app.page.note" } }
        assertEquals("""{"value":"a"}""", actions.last().payload.toString())
    }

    @Test
    fun theStandaloneSearchFieldDispatchesItsRequiredCallbacks() {
        val source =
            """
            {"version":"0.1.0","schemaVersion":"1.23.0",
             "metadata":{"actionBindings":{
               "app.demo.query":{"handlerId":"demo.query","payload":{
                 "query":{"required":true,"type":"string"}},"bound":{}},
               "app.demo.search":{"handlerId":"demo.search","payload":{
                 "query":{"required":true,"type":"string"}},"bound":{}},
               "app.demo.expanded":{"handlerId":"demo.expanded","payload":{
                 "expanded":{"required":true,"type":"boolean"}},"bound":{}}}},
             "root":{"id":"root","type":"Column","props":{},"children":[
               {"id":"root.field","type":"SearchBarInputField","props":{
                 "query":"Initial query",
                 "expanded":false,
                 "onQueryChange":"app.demo.query",
                 "onSearch":"app.demo.search",
                 "onExpandedChange":"app.demo.expanded"},"children":[
                 {"id":"root.field.placeholder","type":"Text","props":{
                   "text":"Search placeholder"},"slot":"placeholder"}]}]}}
            """.trimIndent()
        val actions = mutableListOf<Action>()
        compose.setContent { PyComposeTheme { renderer(actions).Render(parse(source)) } }

        compose.onNodeWithText("Initial query").assertExists()
        compose.onNodeWithText("Search placeholder").assertDoesNotExist()

        compose.onNodeWithText("Initial query").performTextReplacement("Updated query")
        compose.waitUntil(5000) { actions.any { it.actionId == "app.demo.query" } }

        val query = actions.last { it.actionId == "app.demo.query" }
        assertEquals("""{"query":"Updated query"}""", query.payload.toString())
        assertTrue(actions.any { it.actionId == "app.demo.expanded" })

        // A second keystroke must append at the caret, not restart from an older
        // snapshot. The local buffer keeps the field stable until Python echoes.
        compose.onNodeWithText("Updated query").performTextInput("!")
        compose.waitUntil(5000) {
            actions.lastOrNull { it.actionId == "app.demo.query" }?.payload?.toString() ==
                """{"query":"Updated query!"}"""
        }
    }

    private companion object {
        const val FRAME_MS = 100L
    }
}
