package com.pycompose.renderer

import androidx.compose.foundation.pager.PagerState
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.carousel.CarouselState
import androidx.compose.material3.carousel.rememberCarouselState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.saveable.rememberSaveable

/*
 * Positional holders: a pager's page and a carousel's item. The app states the position it
 * wants and the host animates there; the position it settles on, by gesture or by drive, is
 * reported once scrolling comes to rest. How many positions there are is how many children
 * Python sent.
 */

/**
 * The node's pager projection, reporting the page it settles on.
 *
 * @param page Desired page; null leaves paging to gestures.
 * @param report Action id settled pages report to; null reports none.
 * @param count How many pages there are: the children Python sent.
 */
@Composable
fun RenderContext.pagerState(
    page: Long?,
    report: String?,
    count: Int,
): PagerState = rememberHostPagerState(page, report, count, observations::observe)

/**
 * The node's carousel projection, reporting the item it settles on.
 *
 * @param item Desired item; null leaves scrolling to gestures.
 * @param report Action id settled items report to; null reports none.
 * @param count How many items there are: the children Python sent.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun RenderContext.carouselState(
    item: Long?,
    report: String?,
    count: Int,
): CarouselState = rememberHostCarouselState(item, report, count, observations::observe)

/**
 * The host-owned pager holder for one node: it animates to the page the app wants, and
 * reports the page it settles on once paging comes to rest, by gesture or by drive.
 *
 * @param page Desired page; null leaves paging to gestures.
 * @param report Action id settled pages report to; null reports none.
 * @param count How many pages there are, read whenever the pager asks.
 * @param observation Receives the kind, the action id and the settled page.
 */
@Composable
internal fun rememberHostPagerState(
    page: Long?,
    report: String?,
    count: Int,
    observation: Observation,
): PagerState {
    val pages = rememberUpdatedState(count)
    val state = rememberPagerState(initialPage = page?.toInt() ?: 0) { pages.value }
    val lastDesired = rememberSaveable { mutableStateOf<Long?>(null) }
    OnDesired(state, page, answered(report)) { wanted ->
        if (wanted != lastDesired.value) {
            val desired = wanted?.toInt()?.coerceIn(0, (pages.value - 1).coerceAtLeast(0))
            if (desired != null && desired != state.currentPage) state.animateScrollToPage(desired)
            lastDesired.value = wanted
        }
    }
    ObserveIdlePosition(state, { state.currentPage }, "page", report, observation)
    return state
}

/**
 * The host-owned carousel holder for one node: it animates to the item the app wants, and
 * reports the item it settles on once scrolling comes to rest.
 *
 * @param item Desired item; null leaves scrolling to gestures.
 * @param report Action id settled items report to; null reports none.
 * @param count How many items there are, read whenever the carousel asks.
 * @param observation Receives the kind, the action id and the settled item.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun rememberHostCarouselState(
    item: Long?,
    report: String?,
    count: Int,
    observation: Observation,
): CarouselState {
    val items = rememberUpdatedState(count)
    val state = rememberCarouselState(initialItem = item?.toInt() ?: 0) { items.value }
    val lastDesired = rememberSaveable { mutableStateOf<Long?>(null) }
    OnDesired(state, item, answered(report)) { wanted ->
        if (wanted != lastDesired.value) {
            val desired = wanted?.toInt()?.coerceIn(0, (items.value - 1).coerceAtLeast(0))
            if (desired != null && desired != state.currentItem) state.animateScrollToItem(desired)
            lastDesired.value = wanted
        }
    }
    ObserveIdlePosition(state, { state.currentItem }, "currentItem", report, observation)
    return state
}
