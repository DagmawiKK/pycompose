package com.pycompose.host.bridge

import android.content.Context
import android.os.Looper
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import com.pycompose.ir.Handshake

/** No PyObject is retained by Kotlin. Module calls and results stay on the worker. */
class ChaquopyBridge(
    context: Context,
    private val entrypoint: String,
    private val debug: Boolean,
    private val asyncSink: (String, String) -> Unit,
    private val outcomeAdmission: ((String, String) -> Boolean)? = null,
) : BridgeSurface {
    private val application = context.applicationContext
    private var owner: Thread? = null
    private var initialized = false
    private var sessionId = ""

    override fun start(
        route: String,
        restore: String,
    ) {
        check(Thread.currentThread() != Looper.getMainLooper().thread) { "Python on main thread" }
        if (owner == null) owner = Thread.currentThread()
        requireWorker()
        synchronized(startLock) {
            if (!Python.isStarted()) Python.start(AndroidPlatform(application))
        }
        // Each side checks the other speaks its protocol before any session exists.
        Handshake.accept(
            Python
                .getInstance()
                .getModule(MODULE)
                .callAttr("handshake", Handshake.offer())
                .toString(),
        )
        sessionId =
            Python
                .getInstance()
                .getModule(MODULE)
                .callAttr(
                    "start",
                    entrypoint,
                    route,
                    debug,
                    restore,
                    application.filesDir.absolutePath,
                    application.cacheDir.absolutePath,
                ).toString()
        initialized = true
        // Background work needs somewhere to send its results before the app can
        // use it. Registered here, on the worker, so it is never half-installed.
        Python
            .getInstance()
            .getModule(MODULE)
            .callAttr("install_async_sink", asyncSink, outcomeAdmission)
    }

    override fun acceptAction(action: String) {
        requireWorker()
        Python.getInstance().getModule(MODULE).callAttr("accept_action", action)
    }

    override fun fetchLatestSnapshot(): String {
        requireWorker()
        return Python
            .getInstance()
            .getModule(MODULE)
            .callAttr("fetch_latest_snapshot")
            .toString()
    }

    override fun fetchLatest(
        surface: String,
        baseSerial: Long,
    ): String {
        requireWorker()
        return Python
            .getInstance()
            .getModule(MODULE)
            .callAttr("fetch_latest", surface, baseSerial)
            .toString()
    }

    override fun fetchLatestError(): String {
        requireWorker()
        return Python
            .getInstance()
            .getModule(MODULE)
            .callAttr("fetch_latest_error")
            .toString()
    }

    override fun reload(
        route: String,
        restore: String,
    ): Boolean {
        requireWorker()
        if (!debug) return false
        return if (!initialized) {
            start(route, restore)
            true
        } else {
            Python
                .getInstance()
                .getModule(MODULE)
                .callAttr("reload", route, restore)
                .toBoolean()
        }
    }

    override fun close() {
        if (!initialized) return
        requireWorker()
        Python.getInstance().getModule(MODULE).callAttr("close", sessionId)
        initialized = false
    }

    private fun requireWorker() {
        check(owner === Thread.currentThread()) { "Bridge called outside owning worker" }
    }

    companion object {
        private const val MODULE = "pycompose.bridge.runtime"
        private val startLock = Any()
    }
}
