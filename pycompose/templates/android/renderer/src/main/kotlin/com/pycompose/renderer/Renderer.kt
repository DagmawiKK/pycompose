package com.pycompose.renderer

import androidx.compose.foundation.text.BasicText
import androidx.compose.runtime.Composable
import androidx.compose.runtime.key
import androidx.compose.runtime.remember
import com.pycompose.ir.AppBinding
import com.pycompose.ir.AppBindings
import com.pycompose.ir.ValidatedIr
import com.pycompose.ir.generated.IrContract
import com.pycompose.ir.generated.UiNode
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

class RenderContext internal constructor(
    val actions: ActionDispatcher,
    private val renderer: Renderer,
    private val bindings: Map<String, AppBinding>,
) {
    @Composable fun node(node: UiNode) {
        renderer.Node(node, this)
    }

    fun event(
        actionId: String,
        value: JsonPrimitive,
    ) {
        val fields =
            bindings[actionId]?.eventFields ?: IrContract.actionPayloads[actionId].orEmpty()
        val type = if (value.isString) "string" else "boolean"
        val candidates = fields.filterValues { it.type == type }
        if (candidates.size == 1) {
            actions.dispatch(actionId, JsonObject(mapOf(candidates.keys.single() to value)))
        }
    }

    @Composable fun children(nodes: List<UiNode>) {
        nodes.forEach { child -> key(child.id) { node(child) } }
    }
}

/** Stateless registry-driven engine; only wire-validated snapshots enter this seam. */
class Renderer(
    private val registry: ComponentRegistry,
    private val actions: ActionDispatcher,
    private val debug: Boolean = false,
    private val report: (String) -> Unit = {},
) {
    private val modifiers = ModifierBuilder(actions)

    @Composable fun Render(ir: ValidatedIr) {
        val context =
            remember(ir) {
                RenderContext(
                    actions,
                    this,
                    AppBindings.read(ir.snapshot.metadata, ir.snapshot.schemaVersion),
                )
            }
        key(ir.snapshot.root.id) { Node(ir.snapshot.root, context) }
    }

    @Composable internal fun Node(
        node: UiNode,
        context: RenderContext,
    ) {
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
