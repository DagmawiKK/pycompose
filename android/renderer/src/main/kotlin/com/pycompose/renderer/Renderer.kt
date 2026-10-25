@file:OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)

package com.pycompose.renderer

import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.text.BasicText
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import com.pycompose.ir.AppBinding
import com.pycompose.ir.AppBindings
import com.pycompose.ir.Echoes
import com.pycompose.ir.ValidatedIr
import com.pycompose.ir.generated.IrContract
import com.pycompose.ir.generated.UiNode
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull

/**
 * What one node's adapter may do: compose children, reach actions, and report.
 *
 * The surface stays one receiver rather than several collaborators so every
 * hand-written adapter gets the same capabilities through the same parameter.
 * That puts it just over detekt's default function count; splitting it would
 * scatter the host boundary across unrelated types.
 */
@Suppress("TooManyFunctions")
class RenderContext internal constructor(
    val actions: ActionDispatcher,
    internal val renderer: Renderer,
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
    internal val observations =
        ObservationSink(bindings, actions, renderer.report, renderer.reports)

    /**
     * Report one diagnostic for a node the host cannot compose as declared.
     *
     * A hand-written adapter calls this from a one-shot effect keyed by the
     * node, so a recomposition does not repeat it. The message reaches the same
     * sink as the renderer's own diagnostics.
     *
     * @param message The diagnostic to report.
     */
    fun diagnostic(message: String) {
        renderer.report(message)
    }

    /**
     * Ask the app to compose items [first] to [last] of the lazy list keyed [window].
     *
     * @param window The list's window key, as its snapshot stated it.
     * @param first The first item index wanted.
     * @param last The last item index wanted.
     */
    fun requestWindow(
        window: String,
        first: Int,
        last: Int,
    ) {
        renderer.windows(window, first, last)
    }

    /**
     * Ask the app for the window of a lazy list as the user scrolls it (ADR-0043).
     *
     * @param state The list's native state, which knows what is visible.
     * @param window The list's window key, or null for a list stated whole.
     * @param offset The index of the first item the app composed.
     * @param size How many items the app composed.
     */
    @Composable
    fun RequestWindows(
        state: androidx.compose.foundation.lazy.LazyListState,
        window: String?,
        offset: Long?,
        size: Int,
    ) = requestWindows(state, window, offset, size)

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

    /**
     * Keyed content's subtrees for one node: the children Python sent for each key.
     *
     * @param id The node's id, which the subtrees' lifetime follows.
     * @param current The key the snapshot draws now.
     * @param nodes The children Python sent for [current].
     */
    @Composable fun keyedContent(
        id: String,
        current: String,
        nodes: List<UiNode>,
    ): KeyedContent {
        val keyed = remember(id) { KeyedContent() }
        keyed.show(current, this, nodes)
        return keyed
    }

    /** Primary children, in declaration order. */
    @Composable fun children(nodes: List<UiNode>) {
        nodes.unslotted().forEach { child -> key(child.id) { node(child) } }
    }

    /**
     * Primary children composed under the receiver their parent's lambda carries.
     *
     * A scoped component's adapter takes its receiver as a parameter, because the
     * receiver exists only inside the content lambda that provides it. This is
     * how that lambda hands it down; children that need no scope compose exactly
     * as [children] composes them.
     *
     * @param scope The receiver the parent's pinned content lambda carries.
     * @param nodes The parent's child nodes, in declaration order.
     */
    @Composable fun childrenIn(
        scope: Any,
        nodes: List<UiNode>,
    ) {
        nodes.unslotted().forEach { child ->
            key(child.id) { renderer.ScopedNode(child, this, scope) }
        }
    }

    /**
     * A named slot whose native lambda carries a receiver [S], or null when empty.
     *
     * The lambda hands that receiver to each child, as [childrenIn] does. Empty
     * stays null; the generated adapter supplies `{}` for a non-null parameter,
     * preserving the native empty-lambda default.
     */
    fun <S : Any> slotIn(
        nodes: List<UiNode>,
        slot: String,
    ): (@Composable S.() -> Unit)? {
        val filled = nodes.inSlot(slot)
        if (filled.isEmpty()) return null
        return {
            filled.forEach { child ->
                key(child.id) { renderer.ScopedNode(child, this@RenderContext, this) }
            }
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
    internal val windows: (String, Int, Int) -> Unit = { _, _, _ -> },
    internal val report: (String) -> Unit = {},
) {
    private val modifiers = ModifierBuilder(actions)

    /** Report numbers for the session, kept across snapshots. */
    internal val reports = Reports()

    /** Streams each composed holder publishes, by node id, for expressions to read. */
    internal val streams = mutableStateMapOf<String, Map<String, Stream>>()

    @Composable fun Render(ir: ValidatedIr) {
        val context =
            remember(ir) {
                RenderContext(
                    actions,
                    this,
                    AppBindings.read(ir.snapshot.metadata, ir.snapshot.schemaVersion),
                )
            }
        val answered =
            remember(ir) {
                val echoes = Echoes.read(ir.snapshot.metadata)
                val check: (String) -> Boolean = { reports.answered(it, echoes) }
                check
            }
        CompositionLocalProvider(LocalAnswered provides answered) {
            key(ir.snapshot.root.id) { Node(ir.snapshot.root, context) }
        }
    }

    @Composable internal fun Node(
        node: UiNode,
        context: RenderContext,
        scope: Any? = null,
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
        val modifier = modifierFor(node, scope) ?: return
        adapter(node, modifier, context)
    }

    /**
     * Compose one child of a content lambda carrying [scope], through its scoped adapter.
     *
     * A child whose adapter needs another receiver, or none, composes as it
     * would anywhere, still wearing [scope]'s modifiers; a scoped one whose
     * receiver is missing is reported there.
     */
    @Composable internal fun ScopedNode(
        node: UiNode,
        context: RenderContext,
        scope: Any,
    ) {
        val adapter = registry.scoped(node.componentType)
        if (adapter == null || !adapter.scope.isInstance(scope)) {
            Node(node, context, scope)
            return
        }
        val modifier = modifierFor(node, scope) ?: return
        adapter.renderIn(scope, node, modifier, context)
    }

    /** Build one node's modifier, reporting once when the wire carries a bad one. */
    @Composable
    private fun modifierFor(
        node: UiNode,
        scope: Any?,
    ): Modifier? {
        val result = modifiers.build(node.props.modifier, scope)
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
