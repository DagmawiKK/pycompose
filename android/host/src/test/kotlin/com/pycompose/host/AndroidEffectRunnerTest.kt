package com.pycompose.host

import android.app.Activity
import android.content.Intent
import android.os.Looper
import com.pycompose.ir.EffectRequest
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowToast

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class AndroidEffectRunnerTest {
    private val navigated = mutableListOf<String>()
    private val reported = mutableListOf<String>()

    private fun runner(activity: Activity): AndroidEffectRunner =
        AndroidEffectRunner(activity, { navigated.add(it) }, { message -> reported.add(message) })

    private fun request(
        kind: String,
        payload: String = "{}",
    ): EffectRequest = EffectRequest(kind, Json.parseToJsonElement(payload) as JsonObject)

    private fun activity(): Activity = Robolectric.buildActivity(Activity::class.java).setup().get()

    private fun settle() {
        shadowOf(Looper.getMainLooper()).idle()
    }

    @Test
    fun `a toast effect shows exactly the message the app sent`() {
        val host = activity()
        runner(host).runAll(listOf(request("toast", """{"message":"Added Buy milk"}""")))
        settle()
        assertEquals("Added Buy milk", ShadowToast.getTextOfLatestToast())
    }

    @Test
    fun `a navigate effect hands the route to the host and nothing else`() {
        runner(activity()).runAll(listOf(request("navigate", """{"route":"details"}""")))
        settle()
        assertEquals(listOf("details"), navigated)
        assertTrue(reported.toString(), reported.isEmpty())
    }

    @Test
    fun `an openUrl effect asks the system to view exactly that url`() {
        val host = activity()
        runner(host).runAll(listOf(request("openUrl", """{"url":"https://example.com/x"}""")))
        settle()
        val started = shadowOf(host).nextStartedActivity
        assertEquals(Intent.ACTION_VIEW, started.action)
        assertEquals("https://example.com/x", started.data.toString())
        // A handler that cannot cope reports; Robolectric resolves no activity,
        // so the real ActivityNotFoundException path is exercised on device.
        assertTrue(reported.toString(), reported.isEmpty())
    }

    @Test
    fun `every registered kind has a handler, so none is reported as unknown`() {
        runner(activity()).runAll(
            listOf(
                request("toast", """{"message":"hi"}"""),
                request("navigate", """{"route":"home"}"""),
                request("openUrl", """{"url":"https://example.com"}"""),
                request("haptic"),
                request("finish"),
            ),
        )
        settle()
        assertTrue(reported.toString(), reported.isEmpty())
        assertEquals(listOf("home"), navigated)
    }
}
