package com.pycompose.host

import androidx.activity.BackEventCompat
import androidx.activity.ComponentActivity
import androidx.activity.compose.PredictiveBackHandler
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.Stable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.pycompose.host.resources.AndroidResources
import com.pycompose.host.resources.ResourceResolver
import com.pycompose.host.ui.BuiltinComponents
import com.pycompose.renderer.ActionDispatcher
import com.pycompose.renderer.Renderer
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.delay

/** A back gesture in progress: how far it has gone and from which edge. */
@Stable
internal class BackGesture {
    var progress by mutableFloatStateOf(0f)
    var fromLeft by mutableStateOf(true)
}

/**
 * Follow the system back gesture: preview where it leads, then go back on commit.
 *
 * Python owns the back stack, so the gesture only asks for the screen below and,
 * once the user lets go, sends the same back event a button press does. A
 * cancelled gesture leaves everything as it was.
 */
@Composable
internal fun rememberPredictiveBack(model: PyComposeViewModel): BackGesture {
    val gesture = remember { BackGesture() }
    val snapshot by model.snapshot.collectAsStateWithLifecycle()
    var committedAt by remember { mutableStateOf<Any?>(null) }
    PredictiveBackHandler { events ->
        model.previewBelow()
        try {
            events.collect { event ->
                gesture.progress = event.progress
                gesture.fromLeft = event.swipeEdge == BackEventCompat.EDGE_LEFT
            }
            committedAt = snapshot ?: Unit
            model.lifecycle("onBackRequested")
        } catch (cancelled: CancellationException) {
            gesture.progress = 0f
            model.dropPreview()
            throw cancelled
        }
    }
    // A committed gesture keeps its picture until the screen it led to arrives,
    // or briefly, when the app kept its screen.
    LaunchedEffect(committedAt, snapshot) {
        val committed = committedAt ?: return@LaunchedEffect
        if (snapshot === committed) delay(SETTLE_MS)
        gesture.progress = 0f
        model.dropPreview()
        committedAt = null
    }
    return gesture
}

/** The renderer for the preview: a picture, so its taps go nowhere. */
@Composable
internal fun rememberPreviewRenderer(activity: ComponentActivity): Renderer =
    remember(LocalConfiguration.current) {
        Renderer(
            BuiltinComponents.registry(ResourceResolver(AndroidResources(activity))),
            ActionDispatcher {},
            BuildConfig.DEBUG,
        )
    }

/** Shrink and shift the screen being dragged away, as Material's predictive back does. */
internal fun Modifier.predictiveBack(gesture: BackGesture): Modifier =
    graphicsLayer {
        val progress = gesture.progress
        val scale = 1f - SCALE * progress
        scaleX = scale
        scaleY = scale
        translationX = (if (gesture.fromLeft) 1f else -1f) * SHIFT * progress * size.width
        shape = RoundedCornerShape((CORNER * progress).dp)
        clip = progress > 0f
    }

private const val SCALE = 0.1f
private const val SHIFT = 0.05f
private const val CORNER = 32f
private const val SETTLE_MS = 400L
