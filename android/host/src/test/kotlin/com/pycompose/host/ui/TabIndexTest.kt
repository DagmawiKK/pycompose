package com.pycompose.host.ui

import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import com.pycompose.ir.IrParser
import com.pycompose.renderer.ActionDispatcher
import com.pycompose.renderer.Renderer
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/**
 * A tab index outside the tabs degrades instead of crashing the host.
 *
 * Compose reads the tab positions at the selected index while measuring, so an
 * index the app got wrong used to throw from inside composition (ADR-0005).
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34], application = android.app.Application::class)
class TabIndexTest {
    @get:Rule val compose = createComposeRule()

    private fun render(
        kind: String,
        index: Long,
        tabs: List<String>,
    ): List<String> {
        val children =
            tabs.joinToString(",") {
                """{"id":"tab.$it","type":"Text","slot":"tabs","props":{"text":"$it"}}"""
            }
        val source =
            """
            {"version":"0.1.0","schemaVersion":"1.23.0","root":{"id":"tabs","type":"$kind",
              "props":{"selectedTabIndex":$index},"children":[$children]}}
            """.trimIndent()
        val reports = mutableListOf<String>()
        val renderer =
            Renderer(
                BuiltinComponents.registry(),
                ActionDispatcher {},
                debug = true,
                report = { reports.add(it) },
            )
        val ir = IrParser().parse(source).getOrThrow()
        compose.setContent { PyComposeTheme { renderer.Render(ir) } }
        compose.waitForIdle()
        return reports
    }

    @Test
    fun anIndexPastTheTabsSelectsTheLastAndReports() {
        val reports = render("PrimaryTabRow", 5, listOf("One", "Two"))
        compose.onNodeWithText("Two").assertExists()
        assertEquals(listOf("tabs: index 5 is outside its 2 items"), reports)
    }

    @Test
    fun aNegativeIndexSelectsTheFirstAndReports() {
        val reports = render("SecondaryScrollableTabRow", -1, listOf("One", "Two"))
        compose.onNodeWithText("One").assertExists()
        assertEquals(listOf("tabs: index -1 is outside its 2 items"), reports)
    }

    @Test
    fun noTabsComposeNothingAndReport() {
        val reports = render("PrimaryScrollableTabRow", 0, emptyList())
        assertEquals(listOf("tabs: index 0 is outside its 0 items"), reports)
    }

    @Test
    fun anIndexInRangeReportsNothing() {
        val reports = render("SecondaryTabRow", 1, listOf("One", "Two"))
        compose.onNodeWithText("Two").assertExists()
        assertEquals(emptyList<String>(), reports)
    }
}
