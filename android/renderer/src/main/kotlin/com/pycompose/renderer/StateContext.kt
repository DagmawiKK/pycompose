package com.pycompose.renderer

import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.TooltipState
import androidx.compose.runtime.Composable

/**
 * The node's sheet projection, including whether its native sheet is composed.
 *
 * @param open Desired open state; null drives nothing.
 * @param report Action id settled changes report to; null reports none.
 * @param value Desired detent; when present it takes precedence over [open].
 * @param valueReport Action id settled anchors report to; null reports none.
 * @param skipPartiallyExpanded Native partial-anchor policy; null keeps its default.
 */
@Composable
fun RenderContext.sheetState(
    open: Boolean?,
    report: String?,
    value: String? = null,
    valueReport: String? = null,
    skipPartiallyExpanded: Boolean? = null,
): HostSheetState =
    rememberHostSheetState(
        SheetContract(open, report, value, valueReport),
        skipPartiallyExpanded,
        observations,
    )

/**
 * The node's tooltip projection, reporting visibility transitions.
 *
 * @param visible Desired visibility; null leaves the tooltip to its gestures.
 * @param isPersistent Whether the native tooltip waits for an explicit dismissal.
 * @param report Action id visibility changes report to; null reports none.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun RenderContext.tooltipState(
    visible: Boolean?,
    report: String?,
    isPersistent: Boolean,
): TooltipState = rememberHostTooltipState(visible, isPersistent, report, observations::observe)

/**
 * The node's snackbar host, showing a request only for a greater serial.
 *
 * @param id Stable node id the host's lifetime follows.
 * @param actionLabel Optional action beside the message.
 * @param message Content to show.
 * @param onDismiss Action id fulfilled serials report to; null reports none.
 * @param serial Request serial, increased for deliberate repeats.
 */
@Composable
fun RenderContext.snackbar(
    id: String,
    actionLabel: String?,
    message: String,
    onDismiss: String?,
    serial: Long,
): SnackbarHostState =
    rememberHostSnackbar(
        id,
        SnackbarRequest(message, actionLabel, onDismiss, serial),
        observations::observe,
    )
