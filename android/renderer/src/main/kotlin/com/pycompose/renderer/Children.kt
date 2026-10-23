package com.pycompose.renderer

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import com.pycompose.ir.generated.UiNode

/*
 * The two views an adapter takes of its children.
 *
 * The wire keeps primary children and slot fillers in one list and marks the
 * difference with ``slot``, so both views are filters over that list rather
 * than a second field. They are free functions because the list is all they
 * need: an adapter that lists them lazily imports the one it calls.
 */

/** Primary children: the ones no slot claims, in declaration order. */
fun List<UiNode>.unslotted(): List<UiNode> = filter { it.slot == null }

/** Fillers of one declared slot, in declaration order. */
fun List<UiNode>.inSlot(slot: String): List<UiNode> = filter { it.slot == slot }

/**
 * An index into [items], as a Compose parameter that indexes them needs it.
 *
 * Compose reads its items at the index while measuring and throws outside
 * them, so a value the app got wrong would crash the host. Out of range, the
 * nearest item is used and the value is reported once (ADR-0005: degrade,
 * never throw); with no items nothing can be indexed, and null tells the
 * adapter to compose nothing.
 *
 * @param value The index the snapshot states.
 * @param items The items it indexes.
 * @param node The node's id, for the report.
 * @return The index to pass, or null when there are no items.
 */
@Composable
fun RenderContext.index(
    value: Long,
    items: List<UiNode>,
    node: String,
): Int? {
    val count = items.size
    if (value !in 0 until count) {
        LaunchedEffect(node, value, count) {
            diagnostic("$node: index $value is outside its $count items")
        }
    }
    return if (count == 0) null else value.coerceIn(0L, count - 1L).toInt()
}
