package com.pycompose.renderer

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.text.BasicText
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import com.pycompose.ir.IrParser
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import com.pycompose.ir.generated.Column as ColumnNode
import com.pycompose.ir.generated.Text as TextNode

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class RendererTest {
    @get:Rule val compose = createComposeRule()

    @Test
    fun goldenRendersThroughRegisteredAdapters() {
        val source = checkNotNull(javaClass.getResource("/ir_counter.json")).readText()
        val snapshot = IrParser().parse(source).getOrThrow()
        val registry =
            ComponentRegistry
                .Builder()
                .register("Column") { node, modifier, context ->
                    Column(modifier) { context.children((node as ColumnNode).children) }
                }.register("Text") { node, modifier, _ ->
                    BasicText((node as TextNode).props.text, modifier)
                }.build()
        val renderer = Renderer(registry, ActionDispatcher {}, debug = true)
        compose.setContent { renderer.Render(snapshot) }
        compose.onNodeWithText("Hello").assertExists()
        compose.onNodeWithText("Unsupported: FilledButton").assertExists()
    }

    @Test
    fun missingAdapterIsInvisibleInRelease() {
        val snapshot =
            IrParser()
                .parse(
                    checkNotNull(javaClass.getResource("/ir_counter.json")).readText(),
                ).getOrThrow()
        val renderer =
            Renderer(ComponentRegistry.Builder().build(), ActionDispatcher {}, debug = false)
        compose.setContent { renderer.Render(snapshot) }
        compose.onNodeWithText("Unsupported: Column").assertDoesNotExist()
    }
}
