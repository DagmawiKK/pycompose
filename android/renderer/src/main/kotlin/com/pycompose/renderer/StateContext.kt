package com.pycompose.renderer

import androidx.compose.foundation.ScrollState
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.material3.DrawerState
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.SliderState
import androidx.compose.material3.SnackbarHostState
import androidx.compose.runtime.Composable

/**
 * The node's drawer projection, driven only when [open] changes.
 *
 * @param open Desired open state; null drives nothing.
 * @param report Action id settled changes report to; null reports none.
 */
@Composable
fun RenderContext.drawerState(
    open: Boolean?,
    report: String?,
): DrawerState = rememberHostDrawerState(open, report, observations::observe)

/**
 * The node's sheet projection, including whether its native sheet is composed.
 *
 * @param open Desired open state; null drives nothing.
 * @param report Action id settled changes report to; null reports none.
 */
@Composable
fun RenderContext.sheetState(
    open: Boolean?,
    report: String?,
): HostSheetState = rememberHostSheetState(open, report, observations::observe)

/**
 * The node's slider projection; a gesture reports only its finished value.
 *
 * @param value Desired value; null starts at the range's floor.
 * @param report Action id finished values report to; null reports none.
 * @param valueRange Native range; null uses zero to one.
 * @param steps Step count between range bounds; null uses none.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun RenderContext.sliderState(
    value: Double?,
    report: String?,
    valueRange: ClosedFloatingPointRange<Float>?,
    steps: Long?,
): SliderState = rememberHostSliderState(value, report, valueRange, steps, observations::observe)

/**
 * The node's scroll projection, attached through its modifier by the adapter.
 *
 * @param offset Desired offset in pixels; null leaves scrolling to gestures.
 * @param report Action id idle offsets report to; null reports none.
 */
@Composable
fun RenderContext.scrollState(
    offset: Double?,
    report: String?,
): ScrollState = rememberHostScrollState(offset, report, observations::observe)

/**
 * The node's lazy-list projection, reporting the first visible index at rest.
 *
 * @param index Desired first visible item; null leaves scrolling to gestures.
 * @param report Action id idle indexes report to; null reports none.
 */
@Composable
fun RenderContext.lazyListState(
    index: Long?,
    report: String?,
): LazyListState = rememberHostLazyListState(index, report, observations::observe)

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
