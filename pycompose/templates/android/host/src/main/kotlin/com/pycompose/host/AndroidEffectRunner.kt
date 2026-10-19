package com.pycompose.host

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Intent
import android.view.HapticFeedbackConstants
import android.widget.Toast
import androidx.core.net.toUri
import com.pycompose.ir.EffectRequest
import com.pycompose.ir.Effects

/** The host's one effect seam; tests substitute it, the activity supplies it. */
fun interface EffectRunner {
    /**
     * Execute each request once, in order. Called only for a snapshot that
     * actually changed, so effects are never replayed on a repeated pull.
     */
    fun runAll(requests: List<EffectRequest>)
}

/** One native capability behind one registered effect kind. */
private fun interface EffectHandler {
    fun handle(request: EffectRequest)
}

/** Host capabilities the app can ask for. Each one keeps its behaviour native. */
class AndroidEffectRunner(
    private val activity: Activity,
    private val navigate: (String) -> Unit,
    private val report: (String) -> Unit,
) : EffectRunner {
    private val handlers: Map<String, EffectHandler> =
        mapOf(
            "navigate" to
                EffectHandler { request ->
                    onMain { navigate(Effects.string(request, "route")) }
                },
            "finish" to EffectHandler { onMain { activity.finish() } },
            "haptic" to
                EffectHandler {
                    onMain {
                        activity.window.decorView.performHapticFeedback(
                            HapticFeedbackConstants.VIRTUAL_KEY,
                        )
                    }
                },
            "openUrl" to
                EffectHandler { request ->
                    val url = Effects.string(request, "url")
                    onMain {
                        // No resolveActivity: package visibility is restricted
                        // from Android 11, so a missing handler surfaces as itself.
                        try {
                            activity.startActivity(Intent(Intent.ACTION_VIEW, url.toUri()))
                        } catch (_: ActivityNotFoundException) {
                            report("No app can open $url")
                        }
                    }
                },
            "toast" to
                EffectHandler { request ->
                    val message = Effects.string(request, "message")
                    onMain { Toast.makeText(activity, message, Toast.LENGTH_SHORT).show() }
                },
        )

    private fun onMain(block: () -> Unit) {
        activity.runOnUiThread(block)
    }

    /** Execute each request once, in order, reporting kinds this host cannot run. */
    override fun runAll(requests: List<EffectRequest>) {
        for (request in requests) {
            val handler = handlers[request.kind]
            if (handler == null) {
                report("No host runner for effect ${request.kind}")
                continue
            }
            handler.handle(request)
        }
    }
}
