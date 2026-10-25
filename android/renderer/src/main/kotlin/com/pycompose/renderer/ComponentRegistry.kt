package com.pycompose.renderer

import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import com.pycompose.ir.generated.UiNode

typealias NodeRenderer = @Composable (UiNode, Modifier, RenderContext) -> Unit

/** An adapter that composes inside the receiver [S] a parent's content lambda carries. */
typealias ScopedNodeRenderer<S> = @Composable S.(UiNode, Modifier, RenderContext) -> Unit

/** One scoped adapter, with the receiver it composes in. */
internal class Scoped<S : Any>(
    val scope: Class<S>,
    private val render: ScopedNodeRenderer<S>,
) {
    /** Compose inside [receiver], which the caller checked is an [S]. */
    @Composable fun renderIn(
        receiver: Any,
        node: UiNode,
        modifier: Modifier,
        context: RenderContext,
    ) {
        scope.cast(receiver).render(node, modifier, context)
    }
}

/** Immutable adapter table. Registration is explicit; no component dispatch chain. */
class ComponentRegistry private constructor(
    private val adapters: Map<String, NodeRenderer>,
    private val scoped: Map<String, Scoped<*>>,
) {
    operator fun get(type: String): NodeRenderer? = adapters[type]

    /** The scoped adapter for one type, composed only inside its receiver. */
    internal fun scoped(type: String): Scoped<*>? = scoped[type]

    val types: Set<String>
        get() = adapters.keys + scoped.keys

    /** The composition scope a type requires, when only a scoped adapter exists. */
    fun scopeOf(type: String): String? = scoped[type]?.scope?.simpleName

    class Builder {
        private val adapters = linkedMapOf<String, NodeRenderer>()
        private val scoped = linkedMapOf<String, Scoped<*>>()

        fun register(
            type: String,
            renderer: NodeRenderer,
        ): Builder =
            apply {
                claim(type)
                adapters[type] = renderer
            }

        /** Register an adapter that composes only inside a parent providing [scope]. */
        fun <S : Any> registerScoped(
            type: String,
            scope: Class<S>,
            renderer: ScopedNodeRenderer<S>,
        ): Builder =
            apply {
                claim(type)
                scoped[type] = Scoped(scope, renderer)
            }

        /** As the [Class] overload, the receiver named by its type argument. */
        inline fun <reified S : Any> registerScoped(
            type: String,
            noinline renderer: ScopedNodeRenderer<S>,
        ): Builder = registerScoped(type, S::class.java, renderer)

        /** One adapter per type: a scoped one is looked up through its scope alone. */
        private fun claim(type: String) {
            require(type.isNotBlank() && type !in adapters && type !in scoped) {
                "Duplicate/empty adapter: $type"
            }
        }

        fun build(): ComponentRegistry = ComponentRegistry(adapters.toMap(), scoped.toMap())
    }
}
