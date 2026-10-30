package com.pycompose.host

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Intent
import android.view.HapticFeedbackConstants
import android.widget.Toast
import androidx.core.net.toUri
import com.pycompose.ir.EffectRequest
import com.pycompose.ir.generated.Effect

/** The host's one effect seam; tests substitute it, the activity supplies it. */
fun interface EffectRunner {
    /**
     * Execute each request once, in order. Called only for a snapshot that
     * actually changed, so effects are never replayed on a repeated pull.
     */
    fun runAll(requests: List<EffectRequest>)
}

/** Host capabilities the app can ask for. Each one keeps its behaviour native. */
class AndroidEffectRunner(
    private val activity: Activity,
    private val navigate: (String) -> Unit,
    private val pick: (request: String, accept: String) -> Unit,
    private val report: (String) -> Unit,
) : EffectRunner {
    private fun onMain(block: () -> Unit) {
        activity.runOnUiThread(block)
    }

    /**
     * Execute each request once, in order, reporting kinds this host cannot run.
     *
     * The `when` covers every effect the catalog declares, so a new effect
     * without a runner here does not compile.
     */
    override fun runAll(requests: List<EffectRequest>) {
        for (request in requests) {
            val effect = Effect.of(request)
            if (effect == null) {
                report("No host runner for effect ${request.kind}")
                continue
            }
            run(effect)
        }
    }

    private fun run(effect: Effect) {
        when (effect) {
            is Effect.Navigate -> onMain { navigate(effect.route) }
            Effect.Finish -> onMain { activity.finish() }
            Effect.Haptic ->
                onMain {
                    activity.window.decorView.performHapticFeedback(
                        HapticFeedbackConstants.VIRTUAL_KEY,
                    )
                }
            is Effect.OpenUrl ->
                onMain {
                    // No resolveActivity: package visibility is restricted from
                    // Android 11, so a missing handler surfaces as itself.
                    try {
                        activity.startActivity(Intent(Intent.ACTION_VIEW, effect.url.toUri()))
                    } catch (_: ActivityNotFoundException) {
                        report("No app can open ${effect.url}")
                    }
                }
            is Effect.PickFile -> onMain { pick(effect.request, effect.accept) }
            is Effect.Toast ->
                onMain { Toast.makeText(activity, effect.message, Toast.LENGTH_SHORT).show() }
        }
    }
}
