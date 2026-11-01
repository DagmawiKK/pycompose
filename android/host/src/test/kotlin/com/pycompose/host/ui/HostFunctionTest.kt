package com.pycompose.host.ui

import androidx.compose.ui.test.assertAll
import androidx.compose.ui.test.hasClickAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.isEnabled
import androidx.compose.ui.test.isNotEnabled
import androidx.compose.ui.test.junit4.createComposeRule
import com.pycompose.ir.IrParser
import com.pycompose.renderer.ActionDispatcher
import com.pycompose.renderer.Renderer
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/**
 * A value function written in Python runs on the host: the date picker asks it about each
 * day it draws, with no Python in the frame.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34], application = android.app.Application::class)
class HostFunctionTest {
    @get:Rule val compose = createComposeRule()

    // weekdays(utc_time_millis: int) -> bool: (utc_time_millis // DAY + 3) % 7 < 5
    private val weekdays =
        """{"type":"program","params":["integer"],"result":"boolean","body":
           {"op":"lt","args":[{"op":"mod","args":[{"op":"plus","args":[
             {"op":"floorDiv","args":[{"arg":0},{"integer":86400000}]},{"integer":3}]},
             {"integer":7}]},{"integer":5}]}}"""

    private val screen =
        """
        {"version":"0.1.0","schemaVersion":"1.23.0",
         "root":{"id":"root","type":"DatePicker","props":{
           "selectableDates":{"type":"SelectableDates","isSelectableDate":$weekdays}}}}
        """.trimIndent()

    private fun days(name: String) =
        compose.onAllNodes(
            hasText("$name,", substring = true) and hasClickAction(),
        )

    @Test
    fun aDayThePythonFunctionRefusesCannotBePicked() {
        val ir = IrParser().parse(screen).getOrThrow()
        compose.setContent {
            PyComposeTheme {
                Renderer(
                    BuiltinComponents.registry(),
                    ActionDispatcher {},
                ).Render(ir)
            }
        }
        // Whatever month the picker opens on, its weekends are refused and its weekdays not;
        // the year keeps the interface's own answer.
        days("Saturday").assertAll(isNotEnabled())
        days("Sunday").assertAll(isNotEnabled())
        days("Monday").assertAll(isEnabled())
        days("Friday").assertAll(isEnabled())
        assertTrue(days("Monday").fetchSemanticsNodes().size >= 4)
    }
}
