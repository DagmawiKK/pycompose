package com.pycompose.host

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.isSelectable
import androidx.compose.ui.test.isToggleable
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
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
 * Composition scopes: a scoped component composes under the lambda that
 * provides its receiver, never as a component of its own.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34], application = android.app.Application::class)
class ScopedCompositionTest {
    @get:Rule val compose = createComposeRule()

    private val actions = mutableListOf<Action>()

    private fun parse(source: String): ValidatedIr = IrParser().parse(source).getOrThrow()

    private fun renderer(debug: Boolean = false): Renderer =
        Renderer(BuiltinComponents.registry(), ActionDispatcher { actions.add(it) }, debug)

    private fun icon(
        id: String,
        description: String,
        slot: String? = "icon",
    ): String {
        val placed = if (slot == null) "" else ""","slot":"$slot""""
        return """{"id":"$id","type":"Icon","props":{
            "imageVector":{"type":"materialIcon","name":"Filled.Add"},
            "contentDescription":"$description"}$placed}"""
    }

    private fun barItems(): String =
        """
        {"id":"bar","type":"NavigationBar","props":{},"children":[
          {"id":"bar.notes","type":"NavigationBarItem","props":{
            "selected":true,"onClick":"app.demo.notes.1"},"children":[
            ${icon("bar.notes.icon", "Notes icon")},
            {"id":"bar.notes.label","type":"Text","props":{"text":"Notes"},"slot":"label"}]},
          {"id":"bar.about","type":"NavigationBarItem","props":{
            "selected":false,"onClick":"app.demo.about.1"},"children":[
            ${icon("bar.about.icon", "About icon")},
            {"id":"bar.about.label","type":"Text","props":{"text":"About"},"slot":"label"}]}]}
        """.trimIndent()

    @Test
    fun navigationBarItemsComposeUnderTheirProviderAndDispatchTheirOwnAction() {
        // ``NavigationBarItem`` is ``RowScope.``-prefixed in the pin: its
        // receiver exists only inside ``NavigationBar``'s content lambda. The
        // adapter is looked up through the scope, and the label slot proves the
        // call landed inside that lambda rather than somewhere near it.
        val source =
            """
            {"version":"0.1.0","schemaVersion":"1.22.0",
             "metadata":{"actionBindings":{
               "app.demo.notes.1":{"handlerId":"demo.notes","payload":{},"bound":{}},
               "app.demo.about.1":{"handlerId":"demo.about","payload":{},"bound":{}}}},
             "root":{"id":"root","type":"Column","props":{},"children":[${barItems()}]}}
            """.trimIndent()
        compose.setContent { PyComposeTheme { renderer().Render(parse(source)) } }

        compose.onNodeWithText("Notes").assertIsDisplayed()
        compose.onNodeWithText("About").assertIsDisplayed()
        compose.onNodeWithText("About").performClick()
        assertEquals(listOf("app.demo.about.1"), actions.map { it.actionId })
    }

    @Test
    fun aScopedComponentOutsideItsProviderIsReportedRatherThanDrawnWrong() {
        // The same item as the tree's root: no lambda provides the receiver, so
        // there is nothing correct to draw. ADR-0005 says report and degrade.
        val source =
            """
            {"version":"0.1.0","schemaVersion":"1.22.0",
             "root":{"id":"root","type":"NavigationBarItem","props":{
               "selected":false,"onClick":"increment"},"children":[
               {"id":"root.icon","type":"Text","props":{"text":"Stray"},"slot":"icon"}]}}
            """.trimIndent()
        compose.setContent { PyComposeTheme { renderer(debug = true).Render(parse(source)) } }

        compose.onNodeWithText("Unsupported: NavigationBarItem").assertIsDisplayed()
        assertTrue(actions.isEmpty())
    }

    @Test
    fun everyComponentOfTheBatchComposesThroughItsOwnAdapter() {
        // One snapshot holding all twelve: a missing adapter, an unresolved
        // value or a lambda in the wrong shape shows up as an "Unsupported"
        // report while the rest of the tree keeps composing.
        val source =
            """
            {"version":"0.1.0","schemaVersion":"1.22.0",
             "metadata":{"actionBindings":{
               "app.demo.card.1":{"handlerId":"demo.card","payload":{},"bound":{}},
               "app.demo.icon.1":{"handlerId":"demo.icon","payload":{},"bound":{}},
               "app.demo.fab.1":{"handlerId":"demo.fab","payload":{},"bound":{}},
               "app.demo.radio.1":{"handlerId":"demo.radio","payload":{},"bound":{}},
               "app.demo.switch.1":{"handlerId":"demo.switch","payload":{
                 "value":{"required":true,"type":"boolean"}},"bound":{}},
               "app.demo.notes.1":{"handlerId":"demo.notes","payload":{},"bound":{}},
               "app.demo.about.1":{"handlerId":"demo.about","payload":{},"bound":{}}}},
             "root":{"id":"root","type":"Column","props":{},"children":[
               {"id":"root.card","type":"Card","props":{"onClick":"app.demo.card.1"},"children":[
                 {"id":"root.card.text","type":"Text","props":{"text":"Card body"}}]},
               {"id":"root.iconButton","type":"IconButton","props":{
                 "onClick":"app.demo.icon.1"},"children":[
                 ${icon("root.iconButton.icon", "Icon button", slot = null)}]},
               {"id":"root.fab","type":"FloatingActionButton","props":{
                 "onClick":"app.demo.fab.1"},"children":[
                 ${icon("root.fab.icon", "Floating action", slot = null)}]},
               {"id":"root.radio","type":"RadioButton","props":{
                 "selected":true,"onClick":"app.demo.radio.1"}},
               {"id":"root.switch","type":"Switch","props":{
                 "checked":false,"onCheckedChange":"app.demo.switch.1"},"children":[
                 {"id":"root.switch.thumb","type":"Text","props":{"text":"•"},"slot":"thumbContent"}]},
               ${barItems()},
               {"id":"root.dividers","type":"Row","props":{},"children":[
                 {"id":"root.horizontal","type":"HorizontalDivider","props":{"thickness":2}},
                 {"id":"root.vertical","type":"VerticalDivider","props":{}}]},
               {"id":"root.modalSheet","type":"ModalDrawerSheet","props":{},"children":[
                 {"id":"root.modalSheet.text","type":"Text","props":{"text":"Modal drawer body"}}]},
               {"id":"root.dismissibleSheet","type":"DismissibleDrawerSheet","props":{},"children":[
                 {"id":"root.dismissibleSheet.text","type":"Text","props":{"text":"Dismissible drawer body"}}]}]}}
            """.trimIndent()
        compose.setContent { PyComposeTheme { renderer(debug = true).Render(parse(source)) } }

        val unsupported = compose.onAllNodesWithText("Unsupported:", substring = true)
        assertEquals(0, unsupported.fetchSemanticsNodes().size)
        compose.onNodeWithText("Card body").assertExists()
        compose.onNodeWithText("Notes").assertExists()
        compose.onNodeWithText("About").assertExists()
        compose.onNodeWithText("Modal drawer body").assertExists()
        compose.onNodeWithText("Dismissible drawer body").assertExists()

        compose.onNodeWithText("Card body").performClick()
        compose.onNodeWithContentDescription("Icon button").performClick()
        assertEquals(
            listOf("app.demo.card.1", "app.demo.icon.1"),
            actions.map { it.actionId },
        )

        compose.onNode(isToggleable()).performClick()
        assertEquals("""{"value":true}""", actions.last().payload.toString())
        // The radio comes first in the tree; the bar items are selectable too.
        compose.onAllNodes(isSelectable())[0].performClick()
        assertEquals("app.demo.radio.1", actions.last().actionId)
    }

    @Test
    fun anIndeterminateSpinnerComposesWithItsPinnedVocabulary() {
        val source =
            """
            {"version":"0.1.0","schemaVersion":"1.22.0",
             "root":{"id":"root","type":"CircularProgressIndicator","props":{
               "strokeWidth":4,
               "strokeCap":{"type":"StrokeCap","name":"Round"},
               "trackColor":"#33000000"}}}
            """.trimIndent()
        compose.setContent { PyComposeTheme { renderer(debug = true).Render(parse(source)) } }

        assertEquals(
            0,
            compose
                .onAllNodesWithText("Unsupported:", substring = true)
                .fetchSemanticsNodes()
                .size,
        )
    }
}
