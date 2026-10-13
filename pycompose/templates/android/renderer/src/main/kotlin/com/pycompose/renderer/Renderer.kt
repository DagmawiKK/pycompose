package com.pycompose.renderer

import androidx.compose.foundation.text.BasicText
import androidx.compose.runtime.Composable
import androidx.compose.runtime.key
import androidx.compose.runtime.remember
import com.pycompose.ir.ValidatedIr
import com.pycompose.ir.generated.UiNode

class RenderContext internal constructor(
    val actions: ActionDispatcher,
    private val renderer: Renderer,
) {
    @Composable fun node(node: UiNode) {
        renderer.Node(node)
    }

    @Composable fun children(nodes: List<UiNode>) {
        nodes.forEach { child -> key(child.id) { node(child) } }
    }
}

/** Stateless registry-driven engine; only wire-validated snapshots enter this seam. */
class Renderer(
    private val registry: ComponentRegistry,
    actions: ActionDispatcher,
    private val debug: Boolean = false,
    private val report: (String) -> Unit = {},
) {
    private val modifiers = ModifierBuilder(actions)
    private val context = RenderContext(actions, this)

    @Composable fun Render(ir: ValidatedIr) {
        key(ir.snapshot.root.id) { Node(ir.snapshot.root) }
    }

    @Composable internal fun Node(node: UiNode) {
        val adapter = registry[node.componentType]
        val result = remember(node.props.modifier) { modifiers.build(node.props.modifier) }
        val modifier = result.getOrNull()
        if (adapter == null || modifier == null) {
            remember(node.id, node.props, adapter) {
                val reason = result.exceptionOrNull()?.message.orEmpty()
                report(
                    "Cannot render ${node.id}: ${node.componentType}: $reason",
                )
                true
            }
            if (debug) BasicText("Unsupported: ${node.componentType}")
            return
        }
        adapter(node, modifier, context)
    }
}
