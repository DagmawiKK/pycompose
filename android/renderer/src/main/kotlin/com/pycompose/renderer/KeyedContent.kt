package com.pycompose.renderer

import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.key
import com.pycompose.ir.generated.UiNode

/**
 * The subtree keyed content draws for each key it still shows.
 *
 * `AnimatedContent` and `Crossfade` call their content once per key while a
 * transition plays: the outgoing key for as long as it animates out. Python
 * sends only the current key's children, so each key keeps the subtree it last
 * had, and a key is forgotten when Compose stops drawing it.
 */
class KeyedContent internal constructor(
    private val context: RenderContext,
) {
    private val subtrees = mutableMapOf<String, List<UiNode>>()
    private var current: String? = null

    internal fun show(
        key: String,
        nodes: List<UiNode>,
    ) {
        current = key
        subtrees[key] = nodes
    }

    /**
     * Draw one key's subtree.
     *
     * @param scope The receiver the native lambda carries, or null when it has none.
     * @param key The key Compose draws.
     */
    @Composable fun Content(
        scope: Any?,
        key: String,
    ) {
        val nodes = subtrees[key] ?: return
        key(key) {
            if (scope == null) context.children(nodes) else context.childrenIn(scope, nodes)
        }
        DisposableEffect(key) {
            onDispose { if (key != current) subtrees.remove(key) }
        }
    }
}
