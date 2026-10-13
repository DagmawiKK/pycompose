package com.pycompose.renderer

import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import com.pycompose.ir.generated.UiNode

typealias NodeRenderer = @Composable (UiNode, Modifier, RenderContext) -> Unit

/** Immutable adapter table. Registration is explicit; no component dispatch chain. */
class ComponentRegistry private constructor(
    private val adapters: Map<String, NodeRenderer>,
) {
    operator fun get(type: String): NodeRenderer? = adapters[type]

    val types: Set<String> get() = adapters.keys.toSet()

    class Builder {
        private val adapters = linkedMapOf<String, NodeRenderer>()

        fun register(
            type: String,
            renderer: NodeRenderer,
        ): Builder =
            apply {
                require(type.isNotBlank() && type !in adapters) { "Duplicate/empty adapter: $type" }
                adapters[type] = renderer
            }

        fun build(): ComponentRegistry = ComponentRegistry(adapters.toMap())
    }
}
