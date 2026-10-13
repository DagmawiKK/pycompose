package com.pycompose.host

import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import com.pycompose.host.ui.BuiltinComponents
import com.pycompose.host.ui.PyComposeTheme
import com.pycompose.ir.IrParser
import com.pycompose.renderer.Action
import com.pycompose.renderer.ActionDispatcher
import com.pycompose.renderer.Renderer
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34], application = android.app.Application::class)
class BuiltinComponentsTest {
    @get:Rule val compose = createComposeRule()

    @Test fun nativeGoldenAndButtonDispatch() {
        val source = checkNotNull(javaClass.getResource("/component_screen.json")).readText()
        val snapshot = IrParser().parse(source).getOrThrow()
        val actions = mutableListOf<Action>()
        val renderer = Renderer(BuiltinComponents.registry(), ActionDispatcher { actions.add(it) })
        compose.setContent { PyComposeTheme { renderer.Render(snapshot) } }
        compose.onNodeWithText("Hello PyCompose").assertExists()
        compose.onNodeWithText("Ada").assertExists()
        compose.onNodeWithText("Add").performClick()
        assertEquals("increment", actions.single().actionId)
    }
}
