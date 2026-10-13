package com.pycompose.host

import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithContentDescription
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.test.core.app.ApplicationProvider
import com.pycompose.host.resources.AndroidResources
import com.pycompose.host.resources.ResourceResolver
import com.pycompose.host.ui.BuiltinComponents
import com.pycompose.host.ui.PyComposeTheme
import com.pycompose.ir.IrParser
import com.pycompose.ir.generated.IrContract
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
        assertEquals(IrContract.components.keys, BuiltinComponents.registry().types)
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

    @Test fun resourceGoldenUsesRealLocalizedStringsDrawableAndAsset() {
        val source = checkNotNull(javaClass.getResource("/resource_screen.json")).readText()
        val context = ApplicationProvider.getApplicationContext<android.app.Application>()
        val resources = ResourceResolver(AndroidResources(context))
        val renderer = Renderer(BuiltinComponents.registry(resources), ActionDispatcher {})
        val ir = mutableStateOf(IrParser().parse(source).getOrThrow())
        compose.setContent { PyComposeTheme { renderer.Render(ir.value) } }
        val expected = "Bonjour depuis les ressources Android"
        compose.waitUntil(5000) {
            compose.onAllNodesWithText(expected).fetchSemanticsNodes().isNotEmpty() &&
                compose
                    .onAllNodesWithContentDescription("PyCompose logo")
                    .fetchSemanticsNodes()
                    .isNotEmpty() &&
                compose
                    .onAllNodesWithText("This text is loaded from an APK asset.\n")
                    .fetchSemanticsNodes()
                    .isNotEmpty()
        }
        compose.onNodeWithText(expected).assertExists()
        compose.onNodeWithContentDescription("PyCompose logo").assertExists()
        compose.onNodeWithText("This text is loaded from an APK asset.\n").assertExists()
        compose.runOnIdle {
            val plain = source.replace("\"resource\":\"@string/pycompose_greeting\",", "")
            ir.value = IrParser().parse(plain).getOrThrow()
        }
        compose.waitUntil(5000) {
            compose.onAllNodesWithText("Fallback").fetchSemanticsNodes().isNotEmpty()
        }
    }
}
