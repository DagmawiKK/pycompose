package com.pycompose.renderer

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
