package com.pycompose.host

import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.junit4.StateRestorationTester
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.performSemanticsAction
import com.pycompose.host.ui.BuiltinComponents
import com.pycompose.host.ui.PyComposeTheme
import com.pycompose.ir.IrParser
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

/** Detent control observed through the registered renderer, not the holder's internals. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34], application = android.app.Application::class)
class SheetDetentTest {
    @get:Rule val compose = createComposeRule()

    @Test
    fun anExplicitAnchorOpensExpandsAndHidesTheSheet() {
        val ir = mutableStateOf(parse(sheet("hidden")))
        val actions = mutableListOf<Action>()
        val renderer = Renderer(BuiltinComponents.registry(), ActionDispatcher { actions.add(it) })
        compose.setContent { PyComposeTheme { renderer.Render(ir.value) } }
        compose.waitForIdle()
        assertTrue(actions.isEmpty())
        assertTrue(!bodyIsComposed())

        compose.runOnIdle { ir.value = parse(sheet("expanded"), actions) }
        compose.waitForIdle()
        compose.waitUntil(5000) { actions.isNotEmpty() }
        assertEquals(listOf("app.demo.anchor.1"), actions.map { it.actionId })
        assertEquals(listOf("""{"value":"expanded"}"""), actions.map { it.payload.toString() })
        assertTrue(bodyIsComposed())

        compose.runOnIdle { ir.value = parse(sheet("hidden"), actions) }
        compose.waitForIdle()
        compose.waitUntil(5000) { actions.size == 2 }
        assertEquals("""{"value":"hidden"}""", actions.last().payload.toString())
        compose.waitUntil(5000) { !bodyIsComposed() }
    }

    @Test
    fun nativeExpansionCollapseAndDismissalReportTheirActualAnchors() {
        val source = sheet("partiallyExpanded")
        val ir = mutableStateOf(parse(source))
        val actions = mutableListOf<Action>()
        val renderer = Renderer(BuiltinComponents.registry(), ActionDispatcher { actions.add(it) })
        compose.setContent { PyComposeTheme { renderer.Render(ir.value) } }
        compose.waitUntil(5000) { actions.isNotEmpty() }
        assertEquals("""{"value":"partiallyExpanded"}""", actions.last().payload.toString())

        compose
            .onNode(SemanticsMatcher.keyIsDefined(SemanticsActions.Expand))
            .performSemanticsAction(SemanticsActions.Expand)
        compose.waitUntil(5000) { actions.size == 2 }
        assertEquals("""{"value":"expanded"}""", actions.last().payload.toString())
        assertEquals("app.demo.anchor.1", actions.last().actionId)

        // The old desired partial value must not force a native expansion back.
        compose.runOnIdle { ir.value = parse(source, actions) }
        compose.waitForIdle()
        assertEquals(2, actions.size)
        compose
            .onNode(SemanticsMatcher.keyIsDefined(SemanticsActions.Collapse))
            .performSemanticsAction(SemanticsActions.Collapse)
        compose.waitUntil(5000) { actions.size == 3 }
        assertEquals("""{"value":"partiallyExpanded"}""", actions.last().payload.toString())

        compose
            .onNode(SemanticsMatcher.keyIsDefined(SemanticsActions.Dismiss))
            .performSemanticsAction(SemanticsActions.Dismiss)
        compose.waitUntil(5000) { actions.size == 4 }
        assertEquals("""{"value":"hidden"}""", actions.last().payload.toString())
        compose.waitUntil(5000) { !bodyIsComposed() }
    }

    @Test
    fun anUnavailablePartialAnchorOnAnExpandedSheetReportsExpanded() {
        val extra = ",\"skipPartiallyExpanded\":true"
        val ir = mutableStateOf(parse(sheet("expanded", extra = extra)))
        val actions = mutableListOf<Action>()
        val renderer = Renderer(BuiltinComponents.registry(), ActionDispatcher { actions.add(it) })
        compose.setContent { PyComposeTheme { renderer.Render(ir.value) } }
        compose.waitUntil(5000) { actions.size == 1 }
        assertEquals("""{"value":"expanded"}""", actions.last().payload.toString())

        compose.runOnIdle { ir.value = parse(sheet("partiallyExpanded", extra = extra), actions) }
        compose.waitUntil(5000) { actions.size == 2 }
        compose.waitForIdle()
        assertEquals(2, actions.size)
        assertEquals("""{"value":"expanded"}""", actions.last().payload.toString())
        assertTrue(bodyIsComposed())
    }

    @Test
    fun changingSkipDoesNotResurrectADismissedSheet() {
        val ir = mutableStateOf(parse(sheet("expanded")))
        val actions = mutableListOf<Action>()
        val renderer = Renderer(BuiltinComponents.registry(), ActionDispatcher { actions.add(it) })
        compose.setContent { PyComposeTheme { renderer.Render(ir.value) } }
        compose.waitUntil(5000) { actions.size == 1 }
        compose
            .onNode(SemanticsMatcher.keyIsDefined(SemanticsActions.Dismiss))
            .performSemanticsAction(SemanticsActions.Dismiss)
        compose.waitUntil(5000) { !bodyIsComposed() }

        compose.runOnIdle {
            ir.value =
                parse(sheet("expanded", extra = ",\"skipPartiallyExpanded\":true"), actions)
        }
        compose.waitForIdle()
        assertTrue(!bodyIsComposed())
    }

    @Test
    fun changingThePartialPolicyRecreatesAndReconcilesTheHolder() {
        val ir = mutableStateOf(parse(sheet("partiallyExpanded")))
        val actions = mutableListOf<Action>()
        val renderer = Renderer(BuiltinComponents.registry(), ActionDispatcher { actions.add(it) })
        compose.setContent { PyComposeTheme { renderer.Render(ir.value) } }
        compose.waitUntil(5000) { actions.size == 1 }
        assertEquals("""{"value":"partiallyExpanded"}""", actions.last().payload.toString())

        compose.runOnIdle {
            ir.value =
                parse(
                    sheet("partiallyExpanded", extra = ",\"skipPartiallyExpanded\":true"),
                    actions,
                )
        }
        compose.waitUntil(5000) { actions.size == 2 }
        compose.waitForIdle()
        assertEquals(2, actions.size)
        assertEquals("""{"value":"expanded"}""", actions.last().payload.toString())
        assertTrue(bodyIsComposed())
    }

    @Test
    fun dismissalDuringTheOpeningReportsThatTheRequestDidNotCommit() {
        compose.mainClock.autoAdvance = false
        val actions = mutableListOf<Action>()
        val renderer = Renderer(BuiltinComponents.registry(), ActionDispatcher { actions.add(it) })
        val extra = ",\"onOpenChange\":\"app.demo.open.1\""
        compose.setContent {
            PyComposeTheme { renderer.Render(parse(sheet("expanded", extra = extra))) }
        }
        compose.mainClock.advanceTimeBy(100)
        compose
            .onNode(SemanticsMatcher.keyIsDefined(SemanticsActions.Dismiss))
            .performSemanticsAction(SemanticsActions.Dismiss)
        compose.mainClock.advanceTimeBy(3000)
        compose.mainClock.autoAdvance = true

        compose.waitUntil(5000) { actions.size == 2 }
        assertEquals(listOf("app.demo.anchor.1", "app.demo.open.1"), actions.map { it.actionId })
        assertEquals(
            listOf("""{"value":"hidden"}""", """{"open":false}"""),
            actions.map { it.payload.toString() },
        )
        compose.waitForIdle()
        assertEquals(2, actions.size)
        compose.waitUntil(5000) { !bodyIsComposed() }
    }

    @Test
    fun restorationDuringTheOpeningReconcilesTheRequestedAnchor() {
        compose.mainClock.autoAdvance = false
        val actions = mutableListOf<Action>()
        val renderer = Renderer(BuiltinComponents.registry(), ActionDispatcher { actions.add(it) })
        val restoration = StateRestorationTester(compose)
        restoration.setContent { PyComposeTheme { renderer.Render(parse(sheet("expanded"))) } }
        compose.mainClock.advanceTimeBy(100)
        restoration.emulateSavedInstanceStateRestore()
        compose.mainClock.advanceTimeBy(3000)
        compose.mainClock.autoAdvance = true

        compose.waitUntil(5000) { actions.isNotEmpty() }
        compose.waitForIdle()
        assertEquals(1, actions.size)
        assertEquals("""{"value":"expanded"}""", actions.last().payload.toString())
        assertTrue(bodyIsComposed())
    }

    @Test
    fun restorationDuringTheReconcileExpansionKeepsTheRequestedAnchor() {
        compose.mainClock.autoAdvance = false
        val actions = mutableListOf<Action>()
        val renderer = Renderer(BuiltinComponents.registry(), ActionDispatcher { actions.add(it) })
        val restoration = StateRestorationTester(compose)
        restoration.setContent { PyComposeTheme { renderer.Render(parse(sheet("expanded"))) } }
        compose.mainClock.advanceTimeBy(400)
        assertTrue(actions.isEmpty())
        restoration.emulateSavedInstanceStateRestore()
        compose.mainClock.advanceTimeBy(3000)
        compose.mainClock.autoAdvance = true

        compose.waitUntil(5000) { actions.isNotEmpty() }
        compose.waitForIdle()
        assertEquals(1, actions.size)
        assertEquals("""{"value":"expanded"}""", actions.last().payload.toString())
        assertTrue(bodyIsComposed())
    }

    @Test
    fun restorationDuringANativeDismissalStaysAbsent() {
        compose.mainClock.autoAdvance = false
        val actions = mutableListOf<Action>()
        val renderer = Renderer(BuiltinComponents.registry(), ActionDispatcher { actions.add(it) })
        val restoration = StateRestorationTester(compose)
        restoration.setContent { PyComposeTheme { renderer.Render(parse(sheet("expanded"))) } }
        compose.mainClock.advanceTimeBy(1000)
        compose
            .onNode(SemanticsMatcher.keyIsDefined(SemanticsActions.Dismiss))
            .performSemanticsAction(SemanticsActions.Dismiss)
        compose.mainClock.advanceTimeBy(100)
        restoration.emulateSavedInstanceStateRestore()
        compose.mainClock.advanceTimeBy(3000)
        compose.mainClock.autoAdvance = true
        compose.waitForIdle()

        assertTrue(!bodyIsComposed())
    }

    @Test
    fun restorationDuringTheHideStaysAbsent() {
        val ir = mutableStateOf(parse(sheet("expanded")))
        val actions = mutableListOf<Action>()
        val renderer = Renderer(BuiltinComponents.registry(), ActionDispatcher { actions.add(it) })
        val restoration = StateRestorationTester(compose)
        restoration.setContent { PyComposeTheme { renderer.Render(ir.value) } }
        compose.waitUntil(5000) { actions.size == 1 }

        compose.mainClock.autoAdvance = false
        compose.runOnIdle { ir.value = parse(sheet("hidden"), actions) }
        assertTrue(bodyIsComposed())
        restoration.emulateSavedInstanceStateRestore()
        compose.mainClock.advanceTimeBy(3000)
        compose.mainClock.autoAdvance = true

        compose.waitForIdle()
        assertTrue(!bodyIsComposed())
        assertTrue(
            actions
                .drop(1)
                .none { it.payload.toString() == """{"value":"expanded"}""" },
        )
    }

    @Test
    fun restorationKeepsTheNativeAnchorWithoutReplayingAReport() {
        val actions = mutableListOf<Action>()
        val restoration = StateRestorationTester(compose)
        val source = parse(sheet("partiallyExpanded"))
        // The renderer is recreated with the activity, as MainActivity remembers it.
        restoration.setContent {
            val renderer =
                remember {
                    Renderer(
                        BuiltinComponents.registry(),
                        ActionDispatcher { actions.add(it) },
                    )
                }
            PyComposeTheme { renderer.Render(source) }
        }
        compose.waitUntil(5000) { actions.size == 1 }
        compose
            .onNode(SemanticsMatcher.keyIsDefined(SemanticsActions.Expand))
            .performSemanticsAction(SemanticsActions.Expand)
        compose.waitUntil(5000) { actions.size == 2 }

        restoration.emulateSavedInstanceStateRestore()
        compose.waitForIdle()
        assertEquals(2, actions.size)
        // Collapse exists only on the expanded native sheet; the stale Python
        // partial value must neither win restoration nor produce another action.
        assertEquals(
            1,
            compose
                .onAllNodes(SemanticsMatcher.keyIsDefined(SemanticsActions.Collapse))
                .fetchSemanticsNodes()
                .size,
        )
    }

    @Test
    fun aShortSheetReportsExpandedWhenThereIsNoPartialAnchor() {
        assertFallbackToExpanded(sheet("partiallyExpanded", tall = false))
    }

    @Test
    fun skippingPartialExpansionUsesTheNativeExpandedAnchor() {
        assertFallbackToExpanded(
            sheet("partiallyExpanded", extra = ",\"skipPartiallyExpanded\":true"),
        )
    }

    @Test
    fun anExplicitHiddenAnchorTakesPrecedenceOverLegacyOpen() {
        val actions = mutableListOf<Action>()
        val renderer = Renderer(BuiltinComponents.registry(), ActionDispatcher { actions.add(it) })
        compose.setContent {
            PyComposeTheme { renderer.Render(parse(sheet("hidden", extra = ",\"open\":true"))) }
        }
        compose.waitForIdle()
        assertTrue(actions.isEmpty())
        assertTrue(!bodyIsComposed())
    }

    @Test
    fun aDismissedSheetStaysAbsentAcrossRestorationAndAnOldSnapshot() {
        val actions = mutableListOf<Action>()
        val renderer = Renderer(BuiltinComponents.registry(), ActionDispatcher { actions.add(it) })
        val restoration = StateRestorationTester(compose)
        val source = parse(sheet("expanded"))
        restoration.setContent { PyComposeTheme { renderer.Render(source) } }
        compose.waitUntil(5000) { actions.size == 1 }
        compose
            .onNode(SemanticsMatcher.keyIsDefined(SemanticsActions.Dismiss))
            .performSemanticsAction(SemanticsActions.Dismiss)
        compose.waitUntil(5000) { actions.size == 2 }
        compose.waitUntil(5000) { !bodyIsComposed() }
        restoration.emulateSavedInstanceStateRestore()
        compose.waitForIdle()
        assertEquals(2, actions.size)
        assertTrue(!bodyIsComposed())
    }

    @Test
    fun anUnreportedSheetRemainsSilentThroughDetentChanges() {
        val ir = mutableStateOf(parse(sheet("partiallyExpanded", report = false)))
        val actions = mutableListOf<Action>()
        val renderer = Renderer(BuiltinComponents.registry(), ActionDispatcher { actions.add(it) })
        compose.setContent { PyComposeTheme { renderer.Render(ir.value) } }
        compose.waitForIdle()
        assertTrue(bodyIsComposed())
        compose.runOnIdle { ir.value = parse(sheet("expanded", report = false), actions) }
        compose.waitForIdle()
        assertTrue(actions.isEmpty())
        assertEquals(
            1,
            compose
                .onAllNodes(SemanticsMatcher.keyIsDefined(SemanticsActions.Collapse))
                .fetchSemanticsNodes()
                .size,
        )
    }

    @Test
    fun theBooleanObserverReportsPresenceEdgesNotEveryDetent() {
        val extra = ",\"open\":false,\"onOpenChange\":\"app.demo.open.1\""
        val ir = mutableStateOf(parse(sheet("partiallyExpanded", extra = extra)))
        val actions = mutableListOf<Action>()
        val renderer = Renderer(BuiltinComponents.registry(), ActionDispatcher { actions.add(it) })
        compose.setContent { PyComposeTheme { renderer.Render(ir.value) } }
        compose.waitUntil(5000) { actions.size == 2 }
        assertEquals("""{"open":true}""", actions.last().payload.toString())
        assertEquals("app.demo.open.1", actions.last().actionId)

        compose.runOnIdle { ir.value = parse(sheet("expanded", extra = extra), actions) }
        compose.waitForIdle()
        compose.waitUntil(5000) { actions.size == 3 }
        assertEquals("""{"value":"expanded"}""", actions.last().payload.toString())
        assertEquals("app.demo.anchor.1", actions.last().actionId)

        compose.runOnIdle { ir.value = parse(sheet("hidden", extra = extra), actions) }
        compose.waitForIdle()
        compose.waitUntil(5000) { actions.size == 5 }
        assertEquals("""{"open":false}""", actions.last().payload.toString())
        assertEquals("app.demo.open.1", actions.last().actionId)
        assertEquals("app.demo.open.1", actions.last().actionId)
        compose.waitUntil(5000) { !bodyIsComposed() }
    }

    private fun assertFallbackToExpanded(source: String) {
        val actions = mutableListOf<Action>()
        val renderer = Renderer(BuiltinComponents.registry(), ActionDispatcher { actions.add(it) })
        compose.setContent { PyComposeTheme { renderer.Render(parse(source)) } }
        compose.waitUntil(5000) { actions.isNotEmpty() }
        assertEquals(listOf("app.demo.anchor.1"), actions.map { it.actionId })
        assertEquals(listOf("""{"value":"expanded"}"""), actions.map { it.payload.toString() })
        assertTrue(bodyIsComposed())
    }

    private fun bodyIsComposed(): Boolean =
        compose.onAllNodesWithText("Sheet body").fetchSemanticsNodes().isNotEmpty()

    private fun parse(
        source: String,
        actions: List<Action> = emptyList(),
    ) = IrParser().parse(echoing(source, actions)).getOrThrow()

    private fun sheet(
        value: String,
        tall: Boolean = true,
        report: Boolean = true,
        extra: String = "",
    ): String {
        val lines = if (tall) (1..100).joinToString("\\n") { "Body line $it" } else "Short body"
        val callback = if (report) ",\"onValueChange\":\"app.demo.anchor.1\"" else ""
        return """
            {"version":"0.1.0","schemaVersion":"1.23.0","metadata":{"actionBindings":{
              "app.demo.anchor.1":{"handlerId":"demo.anchor","payload":{
                "value":{"required":true,"type":"string"}},"bound":{}},
              "app.demo.open.1":{"handlerId":"demo.open","payload":{
                "open":{"required":true,"type":"boolean"}},"bound":{}}}},
             "root":{"id":"sheet","type":"ModalBottomSheet","props":{
               "value":"$value"$callback$extra},
               "children":[{"id":"body","type":"Text","props":{"text":"Sheet body"}},
                 {"id":"lines","type":"Text","props":{"text":"$lines"}},
                 {"id":"handle","type":"Text","slot":"dragHandle","props":{"text":"Handle"}}]}}
            """.trimIndent()
    }
}
