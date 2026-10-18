package com.pycompose.host

import android.content.res.Configuration
import android.os.Bundle
import android.util.Log
import androidx.activity.ComponentActivity
import androidx.activity.OnBackPressedCallback
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
import androidx.lifecycle.viewmodel.CreationExtras
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.pycompose.host.bridge.ChaquopyBridge
import com.pycompose.host.resources.AndroidResources
import com.pycompose.host.resources.ResourceResolver
import com.pycompose.host.ui.BuiltinComponents
import com.pycompose.host.ui.PyComposeTheme
import com.pycompose.ir.Lifecycle
import com.pycompose.renderer.ActionDispatcher
import com.pycompose.renderer.Renderer
import kotlinx.serialization.json.JsonObject

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
        enableEdgeToEdge()
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
                    ) {
                        Log.w("PyCompose", it)
                    }
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
            darkMode = night == Configuration.UI_MODE_NIGHT_YES,
            locale = configuration.locales[0].toLanguageTag(),
            density = configuration.densityDpi / 160.0,
        )
    }

    private fun reportConfiguration() {
        model.lifecycle("onConfigChanged", configurationPayload())
    }

    /** The activity owns the bridge and the native effect capabilities it exposes. */
    private fun CreationExtras.createModel(): PyComposeViewModel =
        PyComposeViewModel(
            ChaquopyBridge(
                applicationContext,
                BuildConfig.PYCOMPOSE_ENTRYPOINT,
                BuildConfig.DEBUG,
                AsyncResult::deliver,
            ),
            createSavedStateHandle(),
            (application as PyComposeApplication).pythonWorker,
            initialConfig = configurationPayload(),
        )
}
