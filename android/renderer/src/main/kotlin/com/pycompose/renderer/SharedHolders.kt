package com.pycompose.renderer

import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.mutableIntStateOf

/**
 * The holders composed nodes share, by node id.
 *
 * A search bar's expanded surface and its input field use the bar's `SearchBarState`; neither
 * owns one. Each names the node that does, and reads its holder here. A node publishes as it
 * composes, so a descendant or a later sibling finds it in the same pass; a reader that came
 * first waits on [version], which a newly shared holder bumps.
 */
class SharedHolders {
    private val shared = HashMap<String, Any>()
    private val version = mutableIntStateOf(0)

    internal fun put(
        node: String,
        holder: Any,
    ): Boolean = shared.put(node, holder) !== holder

    internal fun remove(
        node: String,
        holder: Any,
    ) {
        if (shared[node] === holder) shared.remove(node)
    }

    internal fun bump() {
        version.intValue++
    }

    internal fun read(node: String): Any? {
        version.intValue
        return shared[node]
    }
}

/**
 * Share this node's holder with any node that names it.
 *
 * @param node This node's id.
 * @param holder The holder it composes with.
 */
@Composable
fun RenderContext.share(
    node: String,
    holder: Any,
) {
    val added = renderer.holders.put(node, holder)
    SideEffect { if (added) renderer.holders.bump() }
    DisposableEffect(node, holder) { onDispose { renderer.holders.remove(node, holder) } }
}

/**
 * The holder of type [T] the named node shares, or null while it has none composed.
 *
 * @param node The id of the node that owns the holder.
 * @return Its holder.
 */
@Composable
inline fun <reified T : Any> RenderContext.shared(node: String): T? = sharedHolder(node) as? T

/** The holder the named node shares, untyped; [shared] is the typed read. */
@PublishedApi
@Composable
internal fun RenderContext.sharedHolder(node: String): Any? = renderer.holders.read(node)
