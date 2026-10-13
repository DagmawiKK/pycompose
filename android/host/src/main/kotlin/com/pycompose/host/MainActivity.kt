package com.pycompose.host

import android.os.Bundle
import android.util.Log
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.createSavedStateHandle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.pycompose.host.bridge.ChaquopyBridge
import com.pycompose.host.ui.BuiltinComponents
import com.pycompose.host.ui.PyComposeTheme
import com.pycompose.renderer.ActionDispatcher
import com.pycompose.renderer.Renderer

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        val factory =
            viewModelFactory {
                initializer {
                    PyComposeViewModel(
                        ChaquopyBridge(
                            applicationContext,
                            BuildConfig.PYCOMPOSE_ENTRYPOINT,
                            BuildConfig.DEBUG,
                        ),
                        createSavedStateHandle(),
                        (application as PyComposeApplication).pythonWorker,
                    )
                }
            }
        setContent {
            val model: PyComposeViewModel = viewModel(factory = factory)
            val snapshot by model.snapshot.collectAsStateWithLifecycle()
            val error by model.error.collectAsStateWithLifecycle()
            LaunchedEffect(error) {
                if (error.isNotEmpty()) Log.w("PyCompose", error)
            }
            val renderer =
                remember(model) {
                    Renderer(
                        BuiltinComponents.registry(),
                        ActionDispatcher(model::dispatch),
                        BuildConfig.DEBUG,
                    ) {
                        Log.w("PyCompose", it)
                    }
                }
            PyComposeTheme {
                Surface(Modifier.fillMaxSize()) {
                    Box {
                        snapshot?.let { renderer.Render(it) }
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
}
