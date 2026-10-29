package com.pycompose.host

import android.content.ComponentCallbacks2
import android.content.res.Configuration
import android.graphics.Color
import android.os.Bundle
import android.util.Log
import androidx.activity.ComponentActivity
import androidx.activity.OnBackPressedCallback
import androidx.activity.SystemBarStyle
import androidx.activity.compose.ReportDrawnWhen
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.createSavedStateHandle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.viewmodel.CreationExtras
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.pycompose.host.bridge.ChaquopyBridge
import com.pycompose.host.bridge.DevSource
import com.pycompose.host.resources.AndroidResources
import com.pycompose.host.resources.ResourceResolver
import com.pycompose.host.ui.AppTheme
import com.pycompose.host.ui.BuiltinComponents
import com.pycompose.host.ui.PyComposeTheme
import com.pycompose.ir.Lifecycle
import com.pycompose.renderer.ActionDispatcher
import com.pycompose.renderer.Renderer
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

class MainActivity : ComponentActivity() {
    private val model: PyComposeViewModel by viewModels {
        viewModelFactory { initializer { createModel() } }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        model.effectRunner =
            AndroidEffectRunner(
                this,
                model::navigate,
            ) { message -> Log.w("PyCompose", message) }
        edgeToEdge()
        followDevServer()
        onBackPressedDispatcher.addCallback(
            this,
            object : OnBackPressedCallback(true) {
                override fun handleOnBackPressed() {
                    model.lifecycle("onBackRequested")
                }
            },
        )
        setContent {
            val snapshot by model.snapshot.collectAsStateWithLifecycle()
            val error by model.error.collectAsStateWithLifecycle()
            // The app's first frame is its first snapshot, not the empty window:
            // what start-up tooling ("Fully drawn") and Baseline Profiles measure.
            ReportDrawnWhen { snapshot != null }
            LaunchedEffect(error) {
                if (error.isNotEmpty()) Log.w("PyCompose", error)
            }
            val renderer =
                remember(model, LocalConfiguration.current) {
                    val resources = ResourceResolver(AndroidResources(this))
                    Renderer(
                        BuiltinComponents.registry(resources),
                        ActionDispatcher(model::dispatch),
                        BuildConfig.DEBUG,
                        report = { Log.w("PyCompose", it) },
                        windows = model::requestWindow,
                    )
                }
            DisposableEffect(model, LocalConfiguration.current) {
                reportConfiguration()
                onDispose { }
            }
            PyComposeTheme {
                Surface(Modifier.fillMaxSize()) {
                    Box(Modifier.safeDrawingPadding()) {
                        snapshot?.let { session ->
                            key(session.epoch) { renderer.Render(session.ir) }
                            ActionTrace.EndOnFrame(session)
                        }
                        if (BuildConfig.DEBUG) {
                            Column(Modifier.align(Alignment.BottomEnd).padding(16.dp)) {
                                if (error.isNotEmpty()) {
                                    Text(
                                        error,
                                        color = MaterialTheme.colorScheme.error,
                                    )
                                }
                                TextButton(onClick = model::reload) { Text("Reload Python") }
                            }
                        }
                    }
                }
            }
        }
    }

    override fun onResume() {
        super.onResume()
        model.lifecycle("onResume")
    }

    @Deprecated("Levels below TRIM_MEMORY_UI_HIDDEN are no longer sent from API 34")
    override fun onTrimMemory(level: Int) {
        super.onTrimMemory(level)
        trimLevel(level)?.let {
            model.lifecycle("onTrimMemory", JsonObject(mapOf("level" to JsonPrimitive(it))))
        }
    }

    override fun onPause() {
        model.lifecycle("onPause")
        super.onPause()
    }

    override fun onDestroy() {
        // Unconditional: this runner holds the Activity, so any runner still
        // attached here is keeping a destroyed context alive.
        model.effectRunner = null
        super.onDestroy()
    }

    /** Draw behind the system bars, with icons matching the theme's dark mode. */
    private fun edgeToEdge() {
        val dark = AppTheme.darkMode ?: return enableEdgeToEdge()
        val bars =
            if (dark) {
                SystemBarStyle.dark(Color.TRANSPARENT)
            } else {
                SystemBarStyle.light(Color.TRANSPARENT, Color.TRANSPARENT)
            }
        enableEdgeToEdge(bars, bars)
    }

    /**
     * Report the current configuration; it is the one fact Python cannot observe
     * itself. The initial report rides the ViewModel's first pull instead, so the
     * first frame the user sees is already painted for this appearance.
     */
    private fun configurationPayload(): JsonObject {
        val configuration = resources.configuration
        val night = configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK
        return Lifecycle.payload(
            orientation =
                Lifecycle.orientation(
                    configuration.orientation == Configuration.ORIENTATION_LANDSCAPE,
                ),
            darkMode = AppTheme.darkMode ?: (night == Configuration.UI_MODE_NIGHT_YES),
            locale = configuration.locales[0].toLanguageTag(),
            density = configuration.densityDpi / 160.0,
        )
    }

    private fun reportConfiguration() {
        model.lifecycle("onConfigChanged", configurationPayload())
    }

    /** The dev server a debug build was launched against (`pycompose run --dev-client`). */
    private val dev: DevSource? by lazy {
        intent.getStringExtra("pycompose.dev.url")?.takeIf { BuildConfig.DEBUG }?.let { url ->
            DevSource(
                url,
                intent.getStringExtra("pycompose.dev.token").orEmpty(),
                intent.getStringExtra("pycompose.dev.source") ?: "app",
                filesDir.resolve("pycompose-dev"),
            )
        }
    }

    /** A dev client follows its dev server: an unchanged bundle reloads nothing. */
    private fun followDevServer() {
        if (dev == null) return
        lifecycleScope.launch {
            while (isActive) {
                delay(DEV_POLL_MS)
                model.reload()
            }
        }
    }

    private companion object {
        const val DEV_POLL_MS = 1_000L

        /** The launch extra that turns on the per-pass log line in a release build. */
        const val TIME_PASSES = "pycompose.timePasses"
    }

    /** The activity owns the bridge and the native effect capabilities it exposes. */
    private fun CreationExtras.createModel(): PyComposeViewModel =
        PyComposeViewModel(
            ChaquopyBridge(
                applicationContext,
                BuildConfig.PYCOMPOSE_ENTRYPOINT,
                BuildConfig.DEBUG,
                AsyncResult::deliver,
                AsyncResult::offer,
                dev,
            ),
            createSavedStateHandle(),
            (application as PyComposeApplication).pythonWorker,
            initialConfig = configurationPayload(),
            // A release build logs its passes only when a measurement asks for it.
            timePasses = BuildConfig.DEBUG || intent.getBooleanExtra(TIME_PASSES, false),
        )
}

/**
 * Android's trim level as the app hears it: the screen went away, the process is
 * cached, or memory is short and the process may go next; null for levels that
 * ask nothing of the app.
 */
@Suppress("DEPRECATION")
internal fun trimLevel(level: Int): String? =
    when {
        level >= ComponentCallbacks2.TRIM_MEMORY_COMPLETE -> "critical"
        level >= ComponentCallbacks2.TRIM_MEMORY_BACKGROUND -> "background"
        level >= ComponentCallbacks2.TRIM_MEMORY_UI_HIDDEN -> "uiHidden"
        level == ComponentCallbacks2.TRIM_MEMORY_RUNNING_CRITICAL -> "critical"
        else -> null
    }
