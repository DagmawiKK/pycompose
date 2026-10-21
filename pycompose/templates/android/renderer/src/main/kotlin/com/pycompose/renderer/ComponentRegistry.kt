@file:OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)

package com.pycompose.renderer

import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.RowScope
import androidx.compose.material3.MultiChoiceSegmentedButtonRowScope
import androidx.compose.material3.SingleChoiceSegmentedButtonRowScope
import androidx.compose.material3.TooltipScope
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import com.pycompose.ir.generated.UiNode

typealias NodeRenderer = @Composable (UiNode, Modifier, RenderContext) -> Unit

typealias RowScopedNodeRenderer = @Composable RowScope.(UiNode, Modifier, RenderContext) -> Unit

typealias ColumnScopedNodeRenderer =
    @Composable ColumnScope.(UiNode, Modifier, RenderContext) -> Unit

typealias BoxScopedNodeRenderer = @Composable BoxScope.(UiNode, Modifier, RenderContext) -> Unit

typealias SingleChoiceScopedNodeRenderer =
    @Composable SingleChoiceSegmentedButtonRowScope.(UiNode, Modifier, RenderContext) -> Unit

typealias MultiChoiceScopedNodeRenderer =
    @Composable MultiChoiceSegmentedButtonRowScope.(UiNode, Modifier, RenderContext) -> Unit

typealias TooltipScopedNodeRenderer =
    @Composable TooltipScope.(UiNode, Modifier, RenderContext) -> Unit

/** Immutable tables for adapters whose receiver is supplied by a native content slot. */
private class ScopedAdapters(
    val row: Map<String, RowScopedNodeRenderer>,
    val column: Map<String, ColumnScopedNodeRenderer>,
    val box: Map<String, BoxScopedNodeRenderer>,
    val singleChoice: Map<String, SingleChoiceScopedNodeRenderer>,
    val multiChoice: Map<String, MultiChoiceScopedNodeRenderer>,
    val tooltip: Map<String, TooltipScopedNodeRenderer>,
)

/** Immutable adapter table. Registration is explicit; no component dispatch chain. */
class ComponentRegistry private constructor(
    private val adapters: Map<String, NodeRenderer>,
    private val scopes: ScopedAdapters,
) {
    operator fun get(type: String): NodeRenderer? = adapters[type]

    /** The RowScope adapter for one type, composed only under a RowScope parent. */
    fun rowScoped(type: String): RowScopedNodeRenderer? = scopes.row[type]

    /** The ColumnScope adapter for one type, composed under a ColumnScope parent. */
    fun columnScoped(type: String): ColumnScopedNodeRenderer? = scopes.column[type]

    /** The BoxScope adapter for one type, composed under a BoxScope parent. */
    fun boxScoped(type: String): BoxScopedNodeRenderer? = scopes.box[type]

    /** The single-choice segmented-row adapter for one type. */
    fun singleChoiceScoped(type: String): SingleChoiceScopedNodeRenderer? =
        scopes.singleChoice[type]

    /** The multi-choice segmented-row adapter for one type. */
    fun multiChoiceScoped(type: String): MultiChoiceScopedNodeRenderer? = scopes.multiChoice[type]

    /** The tooltip-scoped adapter for one type. */
    fun tooltipScoped(type: String): TooltipScopedNodeRenderer? = scopes.tooltip[type]

    val types: Set<String>
        get() =
            adapters.keys +
                scopes.row.keys +
                scopes.column.keys +
                scopes.box.keys +
                scopes.singleChoice.keys +
                scopes.multiChoice.keys +
                scopes.tooltip.keys

    /** The composition scope a type requires, when only a scoped adapter exists. */
    fun scopeOf(type: String): String? =
        when {
            type in scopes.row -> "RowScope"
            type in scopes.column -> "ColumnScope"
            type in scopes.box -> "BoxScope"
            type in scopes.singleChoice -> "SingleChoiceSegmentedButtonRowScope"
            type in scopes.multiChoice -> "MultiChoiceSegmentedButtonRowScope"
            type in scopes.tooltip -> "TooltipScope"
            else -> null
        }

    class Builder {
        private val adapters = linkedMapOf<String, NodeRenderer>()
        private val rowScopedAdapters = linkedMapOf<String, RowScopedNodeRenderer>()
        private val columnScopedAdapters = linkedMapOf<String, ColumnScopedNodeRenderer>()
        private val boxScopedAdapters = linkedMapOf<String, BoxScopedNodeRenderer>()
        private val singleChoiceScopedAdapters =
            linkedMapOf<String, SingleChoiceScopedNodeRenderer>()
        private val multiChoiceScopedAdapters =
            linkedMapOf<String, MultiChoiceScopedNodeRenderer>()
        private val tooltipScopedAdapters = linkedMapOf<String, TooltipScopedNodeRenderer>()

        fun register(
            type: String,
            renderer: NodeRenderer,
        ): Builder =
            apply {
                claim(type)
                adapters[type] = renderer
            }

        fun registerRowScoped(
            type: String,
            renderer: RowScopedNodeRenderer,
        ): Builder =
            apply {
                claim(type)
                rowScopedAdapters[type] = renderer
            }

        fun registerColumnScoped(
            type: String,
            renderer: ColumnScopedNodeRenderer,
        ): Builder =
            apply {
                claim(type)
                columnScopedAdapters[type] = renderer
            }

        fun registerBoxScoped(
            type: String,
            renderer: BoxScopedNodeRenderer,
        ): Builder =
            apply {
                claim(type)
                boxScopedAdapters[type] = renderer
            }

        fun registerSingleChoiceSegmentedButtonRowScoped(
            type: String,
            renderer: SingleChoiceScopedNodeRenderer,
        ): Builder =
            apply {
                claim(type)
                singleChoiceScopedAdapters[type] = renderer
            }

        fun registerMultiChoiceSegmentedButtonRowScoped(
            type: String,
            renderer: MultiChoiceScopedNodeRenderer,
        ): Builder =
            apply {
                claim(type)
                multiChoiceScopedAdapters[type] = renderer
            }

        fun registerTooltipScoped(
            type: String,
            renderer: TooltipScopedNodeRenderer,
        ): Builder =
            apply {
                claim(type)
                tooltipScopedAdapters[type] = renderer
            }

        /** One adapter per type: a scoped one is looked up through its scope alone. */
        private fun claim(type: String) {
            require(
                type.isNotBlank() &&
                    type !in adapters &&
                    type !in rowScopedAdapters &&
                    type !in columnScopedAdapters &&
                    type !in boxScopedAdapters &&
                    type !in singleChoiceScopedAdapters &&
                    type !in multiChoiceScopedAdapters &&
                    type !in tooltipScopedAdapters,
            ) {
                "Duplicate/empty adapter: $type"
            }
        }

        fun build(): ComponentRegistry =
            ComponentRegistry(
                adapters.toMap(),
                ScopedAdapters(
                    rowScopedAdapters.toMap(),
                    columnScopedAdapters.toMap(),
                    boxScopedAdapters.toMap(),
                    singleChoiceScopedAdapters.toMap(),
                    multiChoiceScopedAdapters.toMap(),
                    tooltipScopedAdapters.toMap(),
                ),
            )
    }
}
