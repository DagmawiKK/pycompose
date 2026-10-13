package com.pycompose.host

import android.app.Application
import kotlinx.coroutines.asCoroutineDispatcher
import java.util.concurrent.Executors

/** One process-wide Python thread, surviving activity recreation. Startup is on this worker. */
class PyComposeApplication : Application() {
    val pythonWorker =
        Executors
            .newSingleThreadExecutor { task ->
                Thread(task, "PyCompose-Python")
            }.asCoroutineDispatcher()
}
