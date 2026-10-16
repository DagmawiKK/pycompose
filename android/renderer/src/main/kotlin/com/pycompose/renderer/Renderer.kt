package com.pycompose.renderer

import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.text.BasicText
import androidx.compose.material3.DrawerState
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
    ): MutableInteractionSource? = rememberInteractionSource(id, actionIds, ::observation)

    /**
     * The host-owned drawer state for one node, reconciled to the desired value.
     *
     * The app states the desired value in the snapshot; the host drives the
     * state, gestures and animation included, and reports each settled change
     * through [report]. Null in either leaves that half to the other side.
     *
     * @param open Desired open state; null drives nothing.
     * @param report Action id settled changes report to; null reports none.
     */
    @Composable
    fun drawerState(
        open: Boolean?,
        report: String?,
    ): DrawerState = rememberHostDrawerState(open, report, ::observation)

    /**
     * The host-owned sheet state for one node, and whether to compose the sheet.
     *
     * A sheet has no restful hidden form to sit in: the native component shows
     * itself once composed and keeps its window in front of the app while
     * composed, so the holder also says whether the adapter should compose it.
     * The app states the desired value in the snapshot; the host drives the
     * state, gestures and animation included, and reports each settled change
     * through [report]. Null in either leaves that half to the other side.
     *
     * @param open Desired open state; null drives nothing.
     * @param report Action id settled changes report to; null reports none.
     */
    @Composable
    fun sheetState(
        open: Boolean?,
        report: String?,
    ): HostSheetState = rememberHostSheetState(open, report, ::observation)

    private fun observation(
        kind: String,
        actionId: String,
        value: Boolean,
    ) {
        val fields =
            bindings[actionId]?.eventFields ?: IrContract.actionPayloads[actionId].orEmpty()
        val boolean = fields.filterValues { it.type == "boolean" }
        val field = boolean.keys.singleOrNull()
        if (field == null) {
            // One boolean is the whole observation. Two would mean the host
            // picked a field the app did not mean, so it reports instead.
            renderer.report(
                "Cannot observe $kind for $actionId: " +
                    "${boolean.size} boolean fields among ${fields.keys}",
            )
            return
        }
        actions.dispatch(actionId, JsonObject(mapOf(field to JsonPrimitive(value))))
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

    /** Primary children, in declaration order. */
    fun unslotted(nodes: List<UiNode>): List<UiNode> = nodes.filter { it.slot == null }

    /** Fillers of one declared slot, in declaration order. */
    fun slotNodes(
        nodes: List<UiNode>,
        slot: String,
    ): List<UiNode> = nodes.filter { it.slot == slot }

    @Composable fun children(nodes: List<UiNode>) {
        unslotted(nodes).forEach { child -> key(child.id) { node(child) } }
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
        val filled = slotNodes(nodes, slot)
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
