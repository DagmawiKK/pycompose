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
import kotlinx.serialization.json.booleanOrNull

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
        // A numeric primitive satisfies both numeric declarations: an app's int
        // field is carried as "integer", not "number", so matching one name would
        // silently miss exactly the case this is here to handle.
        val types =
            when {
                value.isString -> setOf("string")
                value.booleanOrNull != null -> setOf("boolean")
                else -> setOf("integer", "number")
            }
        val candidates = fields.filterValues { it.type in types }
        val targetField =
            when {
                candidates.size == 1 -> candidates.keys.single()
                candidates.containsKey("value") -> "value"
                fields.size == 1 -> fields.keys.single()
                else -> null
            }
        if (targetField != null) {
            actions.dispatch(actionId, JsonObject(mapOf(targetField to value)))
        } else {
            renderer.report(
                "Cannot dispatch event for $actionId: no single field accepts " +
                    "${types.joinToString("/")} among ${fields.keys}",
            )
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
    internal val report: (String) -> Unit = {},
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
        val result = modifiers.build(node.props.modifier)
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
