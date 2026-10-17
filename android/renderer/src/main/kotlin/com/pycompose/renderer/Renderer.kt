package com.pycompose.renderer

import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.text.BasicText
import androidx.compose.runtime.Composable
import androidx.compose.runtime.key
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
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

    /**
     * The host-created interaction source for one node, or null when it observes none.
     *
     * Session state returns as an action a frame later; the same-frame reaction the
     * user sees stays the component's own. The source is remembered per node id,
     * so a snapshot pull restarts no interaction in flight.
     *
     * @param id Stable node id the source's lifetime follows.
     * @param actionIds Action observing each interaction kind; null means none.
     */
    @Composable
    fun interactionSource(
        id: String,
        actionIds: Map<String, String?>,
    ): MutableInteractionSource? = rememberInteractionSource(id, actionIds, observations::observe)

    /**
     * Where this context's observations go.
     *
     * The sink fixes the three collaborators an observation needs, so every
     * caller hands the same three-argument function to the state helpers.
     */
    internal val observations = ObservationSink(bindings, actions, renderer.report)

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

    /** Primary children, in declaration order. */
    @Composable fun children(nodes: List<UiNode>) {
        nodes.unslotted().forEach { child -> key(child.id) { node(child) } }
    }

    /**
     * Primary children composed under the RowScope their parent's lambda carries.
     *
     * A scoped component's adapter takes its receiver as a parameter, because the
     * receiver exists only inside the content lambda that provides it. This is
     * how that lambda hands it down; children that need no scope compose exactly
     * as [children] composes them.
     *
     * @param scope The receiver the parent's pinned content lambda carries.
     * @param nodes The parent's child nodes, in declaration order.
     */
    @Composable fun childrenInRowScope(
        scope: RowScope,
        nodes: List<UiNode>,
    ) {
        nodes.unslotted().forEach { child ->
            key(child.id) { renderer.ScopedNode(child, this, scope) }
        }
    }

    /** Primary children composed under their parent's ColumnScope, as [childrenInRowScope]. */
    @Composable fun childrenInColumnScope(
        scope: ColumnScope,
        nodes: List<UiNode>,
    ) {
        nodes.unslotted().forEach { child ->
            key(child.id) { renderer.ScopedNode(child, this, scope) }
        }
    }

    /** Primary children composed under their parent's BoxScope, as [childrenInRowScope]. */
    @Composable fun childrenInBoxScope(
        scope: BoxScope,
        nodes: List<UiNode>,
    ) {
        nodes.unslotted().forEach { child ->
            key(child.id) { renderer.ScopedNode(child, this, scope) }
        }
    }

    /**
     * A slot as a lambda, or null when empty so Compose's default applies.
     *
     * The filled nodes are composed here rather than through [children], which
     * exists to leave slotted children out of the primary subtree -- running
     * them through it a second time composes nothing at all.
     */
    fun slot(
        nodes: List<UiNode>,
        slot: String,
    ): (@Composable () -> Unit)? {
        val filled = nodes.inSlot(slot)
        if (filled.isEmpty()) return null
        return { filled.forEach { child -> key(child.id) { node(child) } } }
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
        if (adapter == null) {
            // A type with only a scoped adapter cannot compose here: its
            // receiver exists inside a parent lambda this path is outside of.
            val scope = registry.scopeOf(node.componentType)
            remember(node.id, node.props) {
                report(
                    "Cannot render ${node.id}: ${node.componentType}: " +
                        (scope?.let { "$it parent required" } ?: ""),
                )
                true
            }
            if (debug) BasicText("Unsupported: ${node.componentType}")
            return
        }
        val modifier = modifierFor(node) ?: return
        adapter(node, modifier, context)
    }

    /** Compose one child of a RowScope content lambda, through its scoped adapter. */
    @Composable internal fun ScopedNode(
        node: UiNode,
        context: RenderContext,
        scope: RowScope,
    ) {
        val adapter = registry.rowScoped(node.componentType)
        if (adapter == null) {
            Node(node, context)
            return
        }
        val modifier = modifierFor(node) ?: return
        scope.adapter(node, modifier, context)
    }

    /** Compose one child of a ColumnScope content lambda, through its scoped adapter. */
    @Composable internal fun ScopedNode(
        node: UiNode,
        context: RenderContext,
        scope: ColumnScope,
    ) {
        val adapter = registry.columnScoped(node.componentType)
        if (adapter == null) {
            Node(node, context)
            return
        }
        val modifier = modifierFor(node) ?: return
        scope.adapter(node, modifier, context)
    }

    /** Compose one child of a BoxScope content lambda, through its scoped adapter. */
    @Composable internal fun ScopedNode(
        node: UiNode,
        context: RenderContext,
        scope: BoxScope,
    ) {
        val adapter = registry.boxScoped(node.componentType)
        if (adapter == null) {
            Node(node, context)
            return
        }
        val modifier = modifierFor(node) ?: return
        scope.adapter(node, modifier, context)
    }

    /** Build one node's modifier, reporting once when the wire carries a bad one. */
    @Composable
    private fun modifierFor(node: UiNode): Modifier? {
        val result = modifiers.build(node.props.modifier)
        val modifier = result.getOrNull()
        if (modifier == null) {
            remember(node.id, node.props) {
                report(
                    "Cannot render ${node.id}: ${node.componentType}: " +
                        result.exceptionOrNull()?.message.orEmpty(),
                )
                true
            }
            if (debug) BasicText("Unsupported: ${node.componentType}")
        }
        return modifier
    }
}
