package com.pycompose.host

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.painter.ColorPainter
import androidx.compose.ui.graphics.painter.Painter
import androidx.compose.ui.text.font.FontFamily
import com.pycompose.host.resources.ResourceBackend
import com.pycompose.host.resources.ResourceResolver
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34], application = android.app.Application::class)
class ResourceResolverTest {
    @Test fun namesAndLocalesAreResolvedAndCached() {
        val backend = FakeResources()
        val resolver = ResourceResolver(backend)
        assertEquals("Bonjour", resolver.string("greeting", "fr").getOrThrow())
        assertEquals("Bonjour", resolver.string("greeting", "fr").getOrThrow())
        assertEquals(1, backend.stringCalls)
        assertEquals("Hello", resolver.string("greeting", "en").getOrThrow())
        assertTrue(resolver.drawable("logo").isSuccess)
        assertEquals("data", resolver.asset("docs/readme.txt").getOrThrow().decodeToString())
        assertEquals(FontFamily.Default, resolver.font("body").getOrThrow())
        resolver.invalidate()
        resolver.string("greeting", "fr")
        assertEquals(3, backend.stringCalls)
    }

    @Test fun missingOrUnsafeNamesReturnFailures() {
        val resolver = ResourceResolver(FakeResources())
        assertTrue(resolver.string("missing").isFailure)
        assertTrue(resolver.drawable("missing").isFailure)
        assertTrue(resolver.font("missing").isFailure)
        assertTrue(resolver.asset("missing.txt").isFailure)
        assertTrue(resolver.drawable("../private").isFailure)
        assertTrue(resolver.asset("docs/../private").isFailure)
        assertTrue(resolver.font("Body").isFailure)
        assertTrue(resolver.string("greeting", "not_a_locale").isFailure)
    }

    private class FakeResources : ResourceBackend {
        var stringCalls = 0

        override fun string(
            name: String,
            locale: String?,
        ): String {
            stringCalls++
            require(name == "greeting") { "missing string" }
            return if (locale == "fr") "Bonjour" else "Hello"
        }

        override fun drawable(name: String): Painter {
            require(name == "logo")
            return ColorPainter(Color.Red)
        }

        override fun asset(name: String): ByteArray {
            require(name == "docs/readme.txt")
            return "data".encodeToByteArray()
        }

        override fun font(name: String): FontFamily {
            require(name == "body")
            return FontFamily.Default
        }

        override fun assetImage(name: String): Painter = ColorPainter(Color.Blue)
    }
}
