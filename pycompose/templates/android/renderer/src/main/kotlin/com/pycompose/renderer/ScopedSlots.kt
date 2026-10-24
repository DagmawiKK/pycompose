@file:OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)

package com.pycompose.renderer

import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.RowScope
import androidx.compose.material3.MultiChoiceSegmentedButtonRowScope
import androidx.compose.material3.SingleChoiceSegmentedButtonRowScope
import androidx.compose.material3.TooltipScope
import androidx.compose.runtime.Composable
import androidx.compose.runtime.key
import com.pycompose.ir.generated.UiNode

/*
 * Named slots whose native lambda carries a scope from the closed vocabulary:
 * each hands that receiver to the scoped children it composes.
 */

/**
 * A named slot whose native lambda carries a RowScope.
 *
 * The returned lambda has the receiver the pinned parameter expects, and
 * passes the same receiver to each child so a scoped child composes under
 * its provider. Empty stays null; the generated adapter supplies `{}` for
 * a non-null parameter, preserving the native empty-lambda default.
 */
fun RenderContext.slotInRowScope(
    nodes: List<UiNode>,
    slot: String,
): (@Composable RowScope.() -> Unit)? {
    val filled = nodes.inSlot(slot)
    if (filled.isEmpty()) return null
    return {
        filled.forEach { child ->
            key(child.id) { renderer.ScopedNode(child, this@slotInRowScope, this) }
        }
    }
}

/** A named slot whose native lambda carries a ColumnScope, as [slotInRowScope]. */
fun RenderContext.slotInColumnScope(
    nodes: List<UiNode>,
    slot: String,
): (@Composable ColumnScope.() -> Unit)? {
    val filled = nodes.inSlot(slot)
    if (filled.isEmpty()) return null
    return {
        filled.forEach { child ->
            key(child.id) { renderer.ScopedNode(child, this@slotInColumnScope, this) }
        }
    }
}

/** A named slot whose native lambda carries a BoxScope, as [slotInRowScope]. */
fun RenderContext.slotInBoxScope(
    nodes: List<UiNode>,
    slot: String,
): (@Composable BoxScope.() -> Unit)? {
    val filled = nodes.inSlot(slot)
    if (filled.isEmpty()) return null
    return {
        filled.forEach { child ->
            key(child.id) { renderer.ScopedNode(child, this@slotInBoxScope, this) }
        }
    }
}

/** A named slot whose lambda carries a single-choice segmented row, as [slotInRowScope]. */
fun RenderContext.slotInSingleChoiceSegmentedButtonRowScope(
    nodes: List<UiNode>,
    slot: String,
): (@Composable SingleChoiceSegmentedButtonRowScope.() -> Unit)? {
    val filled = nodes.inSlot(slot)
    if (filled.isEmpty()) return null
    return {
        filled.forEach { child ->
            key(child.id) {
                renderer.ScopedNode(
                    child,
                    this@slotInSingleChoiceSegmentedButtonRowScope,
                    this,
                )
            }
        }
    }
}

/** A named slot whose lambda carries a multi-choice segmented row, as [slotInRowScope]. */
fun RenderContext.slotInMultiChoiceSegmentedButtonRowScope(
    nodes: List<UiNode>,
    slot: String,
): (@Composable MultiChoiceSegmentedButtonRowScope.() -> Unit)? {
    val filled = nodes.inSlot(slot)
    if (filled.isEmpty()) return null
    return {
        filled.forEach { child ->
            key(child.id) {
                renderer.ScopedNode(
                    child,
                    this@slotInMultiChoiceSegmentedButtonRowScope,
                    this,
                )
            }
        }
    }
}

/** A named slot whose lambda carries a tooltip scope, as [slotInRowScope]. */
fun RenderContext.slotInTooltipScope(
    nodes: List<UiNode>,
    slot: String,
): (@Composable TooltipScope.() -> Unit)? {
    val filled = nodes.inSlot(slot)
    if (filled.isEmpty()) return null
    return {
        filled.forEach { child ->
            key(child.id) {
                renderer.ScopedNode(child, this@slotInTooltipScope, this)
            }
        }
    }
}
