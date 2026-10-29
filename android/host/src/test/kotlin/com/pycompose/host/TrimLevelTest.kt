package com.pycompose.host

import android.content.ComponentCallbacks2
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** Android's trim levels as the app hears them. */
class TrimLevelTest {
    @Suppress("DEPRECATION")
    @Test
    fun `each level the app can act on maps to one name`() {
        assertEquals("uiHidden", trimLevel(ComponentCallbacks2.TRIM_MEMORY_UI_HIDDEN))
        assertEquals("background", trimLevel(ComponentCallbacks2.TRIM_MEMORY_BACKGROUND))
        assertEquals("background", trimLevel(ComponentCallbacks2.TRIM_MEMORY_MODERATE))
        assertEquals("critical", trimLevel(ComponentCallbacks2.TRIM_MEMORY_COMPLETE))
        assertEquals("critical", trimLevel(ComponentCallbacks2.TRIM_MEMORY_RUNNING_CRITICAL))
        assertNull(trimLevel(ComponentCallbacks2.TRIM_MEMORY_RUNNING_LOW))
    }
}
