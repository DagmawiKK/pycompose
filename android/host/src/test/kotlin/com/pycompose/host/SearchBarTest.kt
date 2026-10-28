package com.pycompose.host

import androidx.activity.ComponentActivity
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onNodeWithText
import com.pycompose.host.ui.BuiltinComponents
import com.pycompose.host.ui.PyComposeTheme
import com.pycompose.ir.IrParser
import com.pycompose.ir.ValidatedIr
import com.pycompose.renderer.Action
import com.pycompose.renderer.ActionDispatcher
import com.pycompose.renderer.Renderer
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/**
 * Search bars: the input field is a named slot, suggestions are ColumnScope
 * content, and the expansion callback reports a boolean payload.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34], application = android.app.Application::class)
class SearchBarTest {
    @get:Rule val compose = createAndroidComposeRule<ComponentActivity>()

    private val actions = mutableListOf<Action>()

    private fun parse(source: String): ValidatedIr = IrParser().parse(source).getOrThrow()

    private fun renderer(): Renderer =
        Renderer(BuiltinComponents.registry(), ActionDispatcher { actions.add(it) })

    @Test
    fun searchBarComposesItsInputFieldAndSuggestions() {
        val source =
            """
            {"version":"0.1.0","schemaVersion":"1.23.0",
             "metadata":{"intents":{"demo.search":{"payload":{
                 "expanded":{"required":true,"type":"boolean"}}}}},
             "root":{"id":"root","type":"Column","props":{},"children":[
               {"id":"root.search","type":"SearchBar","props":{
                 "expanded":true,"onExpandedChange":{"fields":{},"intent":"demo.search"}},
                   "children":[
                 {"id":"root.search.field","type":"Text","props":{
                   "text":"Search query"},"slot":"inputField"},
                 {"id":"root.search.suggestion","type":"Text","props":{
                   "text":"Suggestion"}}]}]}}
            """.trimIndent()
        compose.setContent { PyComposeTheme { renderer().Render(parse(source)) } }

        compose.onNodeWithText("Search query").assertIsDisplayed()
        compose.onNodeWithText("Suggestion").assertIsDisplayed()
    }

    @Test
    fun dockedSearchBarComposesTheSameSlotShape() {
        val source =
            """
            {"version":"0.1.0","schemaVersion":"1.23.0",
             "metadata":{"intents":{"demo.docked":{"payload":{
                 "expanded":{"required":true,"type":"boolean"}}}}},
             "root":{"id":"root","type":"Box","props":{},"children":[
               {"id":"root.search","type":"DockedSearchBar","props":{
                 "expanded":true,"onExpandedChange":{"fields":{},"intent":"demo.docked"}},
                   "children":[
                 {"id":"root.search.field","type":"Text","props":{
                   "text":"Docked query"},"slot":"inputField"},
                 {"id":"root.search.suggestion","type":"Text","props":{
                   "text":"Docked suggestion"}}]}]}}
            """.trimIndent()
        compose.setContent { PyComposeTheme { renderer().Render(parse(source)) } }

        compose.onNodeWithText("Docked query").assertIsDisplayed()
        compose.onNodeWithText("Docked suggestion").assertIsDisplayed()
    }

    @Test
    fun anExpandedSearchBarReportsCollapseAsABooleanPayload() {
        val source =
            """
            {"version":"0.1.0","schemaVersion":"1.23.0",
             "metadata":{"intents":{"demo.search":{"payload":{
                 "expanded":{"required":true,"type":"boolean"}}}}},
             "root":{"id":"root","type":"Column","props":{},"children":[
               {"id":"root.search","type":"SearchBar","props":{
                 "expanded":true,"onExpandedChange":{"fields":{},"intent":"demo.search"}},
                   "children":[
                 {"id":"root.search.field","type":"Text","props":{
                   "text":"Search query"},"slot":"inputField"}]}]}}
            """.trimIndent()
        compose.setContent { PyComposeTheme { renderer().Render(parse(source)) } }

        compose.runOnIdle { compose.activity.onBackPressedDispatcher.onBackPressed() }
        compose.waitUntil(5000) { actions.isNotEmpty() }

        assertEquals(intent("demo.search"), actions.single().actionId)
        assertEquals(JsonPrimitive(false), actions.single().payload["expanded"])
    }
}
