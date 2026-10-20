package com.pycompose.renderer

import androidx.compose.foundation.text.BasicText
import androidx.compose.material3.MultiChoiceSegmentedButtonRow
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import com.pycompose.ir.generated.Text
import com.pycompose.ir.generated.TextProps
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/**
 * A segmented row's content lambda carries a receiver of its own. A child
 * registered through that receiver must compose through the row's lambda, not
 * through the generic node path.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class SegmentedScopeTest {
    @get:Rule val compose = createComposeRule()

    private val child = Text(id = "child", props = TextProps(text = "ignored"))

    @Test
    fun aSingleChoiceRowHandsItsReceiverToItsScopedChild() {
        val registry =
            ComponentRegistry
                .Builder()
                .registerSingleChoiceSegmentedButtonRowScoped("Text") { _, modifier, _ ->
                    BasicText("Single scoped", modifier)
                }.build()
        val renderer = Renderer(registry, ActionDispatcher {})
        val context = RenderContext(ActionDispatcher {}, renderer, emptyMap())

        compose.setContent {
            SingleChoiceSegmentedButtonRow {
                context.childrenInSingleChoiceSegmentedButtonRowScope(this, listOf(child))
            }
        }

        compose.onNodeWithText("Single scoped").assertIsDisplayed()
    }

    @Test
    fun aMultiChoiceRowHandsItsReceiverToItsScopedChild() {
        val registry =
            ComponentRegistry
                .Builder()
                .registerMultiChoiceSegmentedButtonRowScoped("Text") { _, modifier, _ ->
                    BasicText("Multi scoped", modifier)
                }.build()
        val renderer = Renderer(registry, ActionDispatcher {})
        val context = RenderContext(ActionDispatcher {}, renderer, emptyMap())

        compose.setContent {
            MultiChoiceSegmentedButtonRow {
                context.childrenInMultiChoiceSegmentedButtonRowScope(this, listOf(child))
            }
        }

        compose.onNodeWithText("Multi scoped").assertIsDisplayed()
    }
}
