package com.pycompose.host.ui

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.isSelectable
import androidx.compose.ui.test.isToggleable
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import com.pycompose.host.intent
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
            "selected":true,"onClick":{"fields":{},"intent":"demo.notes"}},"children":[
            ${icon("bar.notes.icon", "Notes icon")},
            {"id":"bar.notes.label","type":"Text","props":{"text":"Notes"},"slot":"label"}]},
          {"id":"bar.about","type":"NavigationBarItem","props":{
            "selected":false,"onClick":{"fields":{},"intent":"demo.about"}},"children":[
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
             "metadata":{"intents":{"demo.notes":{"payload":{}},"demo.about":{"payload":{}}}},
             "root":{"id":"root","type":"Column","props":{},"children":[${barItems()}]}}
            """.trimIndent()
        compose.setContent { PyComposeTheme { renderer().Render(parse(source)) } }

        compose.onNodeWithText("Notes").assertIsDisplayed()
        compose.onNodeWithText("About").assertIsDisplayed()
        compose.onNodeWithText("About").performClick()
        assertEquals(listOf(intent("demo.about")), actions.map { it.actionId })
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
             "metadata":{"intents":{"demo.card":{"payload":{}},"demo.icon":{"payload":{}},
               "demo.fab":{"payload":{}},"demo.radio":{"payload":{}},"demo.switch":{"payload":{
                 "value":{"required":true,"type":"boolean"}}},"demo.notes":{"payload":{}},
                   "demo.about":{"payload":{}}}},
             "root":{"id":"root","type":"Column","props":{},"children":[
               {"id":"root.card","type":"Card","props":{"onClick":{"fields":{},
                 "intent":"demo.card"}},"children":[
                 {"id":"root.card.text","type":"Text","props":{"text":"Card body"}}]},
               {"id":"root.iconButton","type":"IconButton","props":{
                 "onClick":{"fields":{},"intent":"demo.icon"}},"children":[
                 ${icon("root.iconButton.icon", "Icon button", slot = null)}]},
               {"id":"root.fab","type":"FloatingActionButton","props":{
                 "onClick":{"fields":{},"intent":"demo.fab"}},"children":[
                 ${icon("root.fab.icon", "Floating action", slot = null)}]},
               {"id":"root.radio","type":"RadioButton","props":{
                 "selected":true,"onClick":{"fields":{},"intent":"demo.radio"}}},
               {"id":"root.switch","type":"Switch","props":{
                 "checked":false,"onCheckedChange":{"fields":{},"intent":"demo.switch"}},
                   "children":[
                 {"id":"root.switch.thumb","type":"Text","props":{"text":"•"},
                   "slot":"thumbContent"}]},
               ${barItems()},
               {"id":"root.dividers","type":"Row","props":{},"children":[
                 {"id":"root.horizontal","type":"HorizontalDivider","props":{"thickness":2}},
                 {"id":"root.vertical","type":"VerticalDivider","props":{}}]},
               {"id":"root.modalSheet","type":"ModalDrawerSheet","props":{},"children":[
                 {"id":"root.modalSheet.text","type":"Text","props":{"text":"Modal drawer body"}}]},
               {"id":"root.dismissibleSheet","type":"DismissibleDrawerSheet","props":{},"children":[
                 {"id":"root.dismissibleSheet.text","type":"Text",
                   "props":{"text":"Dismissible drawer body"}}]}]}}
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
            listOf(intent("demo.card"), intent("demo.icon")),
            actions.map { it.actionId },
        )

        compose.onNode(isToggleable()).performClick()
        assertEquals("""{"value":true}""", actions.last().payload.toString())
        // The radio comes first in the tree; the bar items are selectable too.
        compose.onAllNodes(isSelectable())[0].performClick()
        assertEquals(intent("demo.radio"), actions.last().actionId)
    }

    @Test
    fun aScopedNamedSlotComposesItsChildThroughTheProvidedReceiver() {
        // ``actions`` carries RowScope; ``NavigationBarItem`` needs exactly
        // that receiver.  Placing it there proves the named-slot renderer
        // hands the scope down instead of falling back to the unscoped path.
        val source =
            """
            {"version":"0.1.0","schemaVersion":"1.23.0",
             "metadata":{"intents":{"demo.item":{"payload":{}}}},
             "root":{"id":"root","type":"TopAppBar","props":{},"children":[
               {"id":"root.title","type":"Text","props":{"text":"Title"},"slot":"title"},
               {"id":"root.actions","type":"NavigationBarItem","props":{
                 "selected":true,"onClick":{"fields":{},"intent":"demo.item"}},"slot":"actions",
                   "children":[
                 {"id":"root.actions.icon","type":"Text","props":{"text":"Icon"},
                  "slot":"icon"},
                 {"id":"root.actions.label","type":"Text","props":{"text":"Action label"},
                  "slot":"label"}]}]}}
            """.trimIndent()
        compose.setContent { PyComposeTheme { renderer().Render(parse(source)) } }

        // A NavigationBarItem fills its RowScope, so it can squeeze the title;
        // the proof is that the row-scoped child itself composes and clicks.
        compose.onNodeWithText("Action label").assertIsDisplayed()
        compose.onNodeWithText("Action label").performClick()
        assertEquals(listOf(intent("demo.item")), actions.map { it.actionId })
    }

    @Test
    fun anIndeterminateSpinnerComposesWithItsPinnedVocabulary() {
        val source =
            """
            {"version":"0.1.0","schemaVersion":"1.22.0",
             "root":{"id":"root","type":"CircularProgressIndicator","props":{
               "strokeWidth":4,
               "strokeCap":{"type":"StrokeCap","name":"Round"},
               "trackColor":{"type":"Color","color":855638016}}}}
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

    @Test
    fun aMenuAnchorOpensItsExposedDropdownMenu() {
        // ``menuAnchor`` is a member of ExposedDropdownMenuBoxScope: worn on the
        // box's child, the click reaches onExpandedChange, which is the only way
        // the menu ever opens.
        val source =
            """
            {"version":"0.1.0","schemaVersion":"1.23.0",
             "metadata":{"intents":{"demo.open":{"payload":{
                 "expanded":{"required":true,"type":"boolean"}}}}},
             "root":{"id":"root","type":"ExposedDropdownMenuBox","props":{
               "expanded":false,"onExpandedChange":{"fields":{},"intent":"demo.open"}},"children":[
               {"id":"root.anchor","type":"Text","props":{"text":"Choose a fruit",
                 "modifier":{"operations":[{"type":"menuAnchor",
                   "menuAnchorType":{"type":"ExposedDropdownMenuAnchorType",
                     "name":"PrimaryNotEditable"},"enabled":true}]}}}]}}
            """.trimIndent()
        compose.setContent { PyComposeTheme { renderer(debug = true).Render(parse(source)) } }

        compose.onNodeWithText("Choose a fruit").performClick()
        assertEquals(listOf(intent("demo.open")), actions.map { it.actionId })
        assertEquals("""{"expanded":true}""", actions.last().payload.toString())
    }

    @Test
    fun weightSharesARowBetweenTheChildrenWearingIt() {
        val source =
            """
            {"version":"0.1.0","schemaVersion":"1.23.0",
             "root":{"id":"root","type":"Row","props":{
               "modifier":{"operations":[{"type":"size","width":300,"height":40}]}},
               "children":[
               {"id":"root.a","type":"Text","props":{"text":"A",
                 "modifier":{"operations":[{"type":"weight","weight":1}]}}},
               {"id":"root.b","type":"Text","props":{"text":"B",
                 "modifier":{"operations":[{"type":"weight","weight":2}]}}}]}}
            """.trimIndent()
        compose.setContent { PyComposeTheme { renderer().Render(parse(source)) } }

        val a =
            compose
                .onNodeWithText("A")
                .fetchSemanticsNode()
                .size.width
        val b =
            compose
                .onNodeWithText("B")
                .fetchSemanticsNode()
                .size.width
        assertEquals(2 * a.toDouble(), b.toDouble(), 2.0)
    }

    @Test
    fun aScopedModifierOutsideItsScopeIsReportedRatherThanDropped() {
        // A Column carries ColumnScope, not the menu box's: nothing correct
        // can anchor there, so the node degrades and says why.
        val reports = mutableListOf<String>()
        val source =
            """
            {"version":"0.1.0","schemaVersion":"1.23.0",
             "root":{"id":"root","type":"Column","props":{},"children":[
               {"id":"root.stray","type":"Text","props":{"text":"Stray",
                 "modifier":{"operations":[{"type":"menuAnchor",
                   "menuAnchorType":{"type":"ExposedDropdownMenuAnchorType",
                     "name":"PrimaryNotEditable"}}]}}}]}}
            """.trimIndent()
        val renderer =
            Renderer(
                BuiltinComponents.registry(),
                ActionDispatcher { actions.add(it) },
                debug = true,
                report = { reports.add(it) },
            )
        compose.setContent { PyComposeTheme { renderer.Render(parse(source)) } }

        compose.onNodeWithText("Unsupported: Text").assertIsDisplayed()
        assertEquals(
            listOf("Cannot render root.stray: Text: menuAnchor needs a parent declaring it"),
            reports,
        )
    }
}
