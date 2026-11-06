package com.pycompose.host.ui

import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.getBoundsInRoot
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
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

/** The lazy grids, generated: cells from the pin's GridCells, items as a list's are. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34], application = android.app.Application::class)
class GridTest {
    @get:Rule val compose = createComposeRule()

    @Test
    fun aFixedGridLaysItsChildrenOutInColumnsAndTravelsToAStatedItem() {
        val ir = mutableStateOf(parse(grid(first = null)))
        val actions = mutableListOf<Action>()
        compose.setContent {
            PyComposeTheme {
                Renderer(BuiltinComponents.registry(), ActionDispatcher { actions.add(it) })
                    .Render(ir.value)
            }
        }
        compose.waitForIdle()

        // Two columns: the second cell sits beside the first, the third below it.
        val first = compose.onNodeWithText("Cell 0").getBoundsInRoot()
        val second = compose.onNodeWithText("Cell 1").getBoundsInRoot()
        val third = compose.onNodeWithText("Cell 2").getBoundsInRoot()
        assertEquals(first.top, second.top)
        assertTrue(second.left > first.left)
        assertEquals(first.left, third.left)
        assertTrue(third.top > first.top)

        compose.runOnIdle { ir.value = parse(grid(first = 40)) }
        compose.waitForIdle()
        compose.waitUntil(5000) { actions.isNotEmpty() }
        assertEquals(JsonPrimitive(40), actions.last().payload["firstVisibleItemIndex"])
    }

    private fun parse(source: String): ValidatedIr = IrParser().parse(source).getOrThrow()

    private fun grid(first: Int?): String {
        val cells =
            (0 until 100).joinToString(",") {
                """{"id":"c$it","type":"Text","props":{"text":"Cell $it"}}"""
            }
        val stated = first?.let { ",\"firstVisibleItemIndex\":$it" } ?: ""
        return """
            {"version":"0.1.0","schemaVersion":"1.23.0","metadata":{"intents":{
              "demo.grid":{"payload":{"firstVisibleItemIndex":{"required":true,"type":"integer"}}}}},
             "root":{"id":"grid","type":"LazyVerticalGrid","props":{
               "columns":{"type":"GridCellsFixed","count":2},
               "onFirstVisibleItemIndexSettled":{"fields":{},"intent":"demo.grid"}$stated},
               "children":[$cells]}}
            """.trimIndent()
    }
}
