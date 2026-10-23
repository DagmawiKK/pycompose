package com.pycompose.renderer

import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.lazy.items
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.pycompose.ir.generated.UiNode

/** Items composed beyond what is visible, on each side, before the user reaches them. */
private const val PREFETCH = 20

/** The height an item not yet composed by the app takes while its window is on the way. */
private val PLACEHOLDER = 56.dp

/**
 * List a lazy container's children, which may be a window of a longer list (ADR-0043).
 *
 * A container that states [count] has that many items, of which [nodes] are the ones the
 * app composed, starting at index [offset]; the rest hold a placeholder until their window
 * arrives. A container that states no count lists its children as they are.
 */
fun LazyListScope.windowedItems(
    context: RenderContext,
    nodes: List<UiNode>,
    count: Long?,
    offset: Long?,
) {
    if (count == null) {
        items(nodes, key = { it.id }) { context.node(it) }
        return
    }
    val first = (offset ?: 0L).toInt()
    items(
        count.toInt(),
        key = { index -> nodes.getOrNull(index - first)?.id ?: "pycompose.pending.$index" },
    ) { index ->
        val node = nodes.getOrNull(index - first)
        if (node !=
            null
        ) {
            context.node(node)
        } else {
            Spacer(Modifier.fillMaxWidth().height(PLACEHOLDER))
        }
    }
}

/**
 * Ask the app for the window of a list as the user scrolls it.
 *
 * Whenever what is visible, with [PREFETCH] items either side, reaches past the window the
 * app composed, the host asks for the wider one; the app answers with a new snapshot.
 *
 * @param state The list's native state, which knows what is visible.
 * @param window The list's window key, or null for a list stated whole.
 * @param offset The index of the first item the app composed.
 * @param size How many items the app composed.
 */
@Composable
internal fun RenderContext.requestWindows(
    state: LazyListState,
    window: String?,
    offset: Long?,
    size: Int,
) {
    if (window == null) return
    val start = (offset ?: 0L).toInt()
    val held = rememberUpdatedState(start until start + size)
    LaunchedEffect(state, window) {
        snapshotFlow {
            state.layoutInfo.visibleItemsInfo.let {
                it.firstOrNull()?.index to
                    it.lastOrNull()?.index
            }
        }.collect { (first, last) ->
            if (first == null || last == null) return@collect
            val total = state.layoutInfo.totalItemsCount
            val wanted = maxOf(0, first - PREFETCH)..minOf(total - 1, last + PREFETCH)
            if (wanted.first < held.value.first || wanted.last > held.value.last) {
                requestWindow(window, wanted.first, wanted.last)
            }
        }
    }
}
