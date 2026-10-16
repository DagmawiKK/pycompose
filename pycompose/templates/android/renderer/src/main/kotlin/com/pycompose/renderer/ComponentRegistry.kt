package com.pycompose.renderer

import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.RowScope
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import com.pycompose.ir.generated.UiNode

typealias NodeRenderer = @Composable (UiNode, Modifier, RenderContext) -> Unit

typealias RowScopedNodeRenderer = @Composable RowScope.(UiNode, Modifier, RenderContext) -> Unit

typealias ColumnScopedNodeRenderer =
    @Composable ColumnScope.(UiNode, Modifier, RenderContext) -> Unit

typealias BoxScopedNodeRenderer = @Composable BoxScope.(UiNode, Modifier, RenderContext) -> Unit

/** Immutable adapter table. Registration is explicit; no component dispatch chain. */
class ComponentRegistry private constructor(
    private val adapters: Map<String, NodeRenderer>,
    private val rowScopedAdapters: Map<String, RowScopedNodeRenderer>,
    private val columnScopedAdapters: Map<String, ColumnScopedNodeRenderer>,
    private val boxScopedAdapters: Map<String, BoxScopedNodeRenderer>,
) {
    operator fun get(type: String): NodeRenderer? = adapters[type]

    /** The RowScope adapter for one type, composed only under a RowScope parent. */
    fun rowScoped(type: String): RowScopedNodeRenderer? = rowScopedAdapters[type]

    /** The ColumnScope adapter for one type, composed under a ColumnScope parent. */
    fun columnScoped(type: String): ColumnScopedNodeRenderer? = columnScopedAdapters[type]

    /** The BoxScope adapter for one type, composed under a BoxScope parent. */
    fun boxScoped(type: String): BoxScopedNodeRenderer? = boxScopedAdapters[type]

    val types: Set<String>
        get() =
            adapters.keys +
                rowScopedAdapters.keys +
                columnScopedAdapters.keys +
                boxScopedAdapters.keys

    /** The composition scope a type requires, when only a scoped adapter exists. */
    fun scopeOf(type: String): String? =
        when {
            type in rowScopedAdapters -> "RowScope"
            type in columnScopedAdapters -> "ColumnScope"
            type in boxScopedAdapters -> "BoxScope"
            else -> null
        }

    class Builder {
        private val adapters = linkedMapOf<String, NodeRenderer>()
        private val rowScopedAdapters = linkedMapOf<String, RowScopedNodeRenderer>()
        private val columnScopedAdapters = linkedMapOf<String, ColumnScopedNodeRenderer>()
        private val boxScopedAdapters = linkedMapOf<String, BoxScopedNodeRenderer>()

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

        /** One adapter per type: a scoped one is looked up through its scope alone. */
        private fun claim(type: String) {
            require(
                type.isNotBlank() &&
                    type !in adapters &&
                    type !in rowScopedAdapters &&
                    type !in columnScopedAdapters &&
                    type !in boxScopedAdapters,
            ) {
                "Duplicate/empty adapter: $type"
            }
        }

        fun build(): ComponentRegistry =
            ComponentRegistry(
                adapters.toMap(),
                rowScopedAdapters.toMap(),
                columnScopedAdapters.toMap(),
                boxScopedAdapters.toMap(),
            )
    }
}
