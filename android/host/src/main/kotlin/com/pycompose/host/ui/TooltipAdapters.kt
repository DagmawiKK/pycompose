@file:OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)

package com.pycompose.host.ui

import androidx.compose.material3.PlainTooltip
import androidx.compose.material3.RichTooltip
import androidx.compose.material3.TooltipAnchorPosition
import androidx.compose.material3.TooltipBox
import androidx.compose.material3.TooltipDefaults
import androidx.compose.material3.TooltipScope
import androidx.compose.ui.unit.dp
import com.pycompose.renderer.ComponentRegistry
import com.pycompose.renderer.TooltipPropResolver
import com.pycompose.renderer.tooltipState
import com.pycompose.ir.generated.PlainTooltip as PlainTooltipNode
import com.pycompose.ir.generated.RichTooltip as RichTooltipNode
import com.pycompose.ir.generated.TooltipBox as TooltipBoxNode

/** The native tooltip scope and visibility projection stay entirely host-local. */
internal fun ComponentRegistry.Builder.tooltips(): ComponentRegistry.Builder =
    register("TooltipBox") { node, modifier, context ->
        val box = node as TooltipBoxNode
        val state =
            context.tooltipState(
                visible = box.props.visible,
                report = box.props.onVisibilityChange,
                isPersistent = box.props.isPersistent,
            )
        TooltipBox(
            positionProvider =
                TooltipDefaults.rememberTooltipPositionProvider(
                    TooltipPropResolver
                        .tooltipPosition(box.props.position)
                        .getOrDefault(TooltipAnchorPosition.Above),
                ),
            tooltip = context.slotIn<TooltipScope>(box.children, "tooltip") ?: {},
            state = state,
            modifier = modifier,
            onDismissRequest = { state.dismiss() },
            focusable = box.props.focusable,
            enableUserInput = box.props.enableUserInput,
            hasAction = box.props.hasAction,
            content = { context.children(box.children) },
        )
    }.plainTooltips().richTooltips()

private fun ComponentRegistry.Builder.plainTooltips(): ComponentRegistry.Builder =
    registerScoped<TooltipScope>("PlainTooltip") { node, modifier, context ->
        val tip = node as PlainTooltipNode
        PlainTooltip(
            modifier = modifier,
            caretShape = if (tip.props.showCaret) TooltipDefaults.caretShape() else null,
            maxWidth = tip.props.maxWidth?.dp ?: TooltipDefaults.plainTooltipMaxWidth,
            contentColor =
                tip.props.contentColor?.let { nativeColor(it) }
                    ?: TooltipDefaults.plainTooltipContentColor,
            containerColor =
                tip.props.containerColor?.let { nativeColor(it) }
                    ?: TooltipDefaults.plainTooltipContainerColor,
            content = { context.children(tip.children) },
        )
    }

private fun ComponentRegistry.Builder.richTooltips(): ComponentRegistry.Builder =
    registerScoped<TooltipScope>("RichTooltip") { node, modifier, context ->
        val tip = node as RichTooltipNode
        RichTooltip(
            modifier = modifier,
            title = context.slot(tip.children, "title"),
            action = context.slot(tip.children, "action"),
            caretShape = if (tip.props.showCaret) TooltipDefaults.caretShape() else null,
            maxWidth = tip.props.maxWidth?.dp ?: TooltipDefaults.richTooltipMaxWidth,
            colors =
                TooltipDefaults.richTooltipColors(
                    containerColor = nativeColor(tip.props.containerColor),
                    contentColor = nativeColor(tip.props.contentColor),
                    titleContentColor = nativeColor(tip.props.titleContentColor),
                    actionContentColor = nativeColor(tip.props.actionContentColor),
                ),
            text = { context.children(tip.children) },
        )
    }
