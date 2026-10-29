package com.pycompose.host.resources

import android.util.LruCache
import androidx.compose.ui.geometry.isSpecified
import androidx.compose.ui.graphics.painter.Painter
import androidx.compose.ui.text.font.FontFamily
import com.pycompose.ir.ResourceReference

/** Narrow resource seam: fakeable without R classes or Python/platform objects. */
interface ResourceBackend {
    fun string(
        name: String,
        locale: String?,
    ): String

    fun drawable(name: String): Painter

    fun asset(name: String): ByteArray

    fun font(name: String): FontFamily

    fun assetImage(name: String): Painter

    /** An image Python wrote to the app's media cache, by its content-digest name. */
    fun fileImage(name: String): Painter = error("No media files: $name")
}

/** Configuration-scoped, name-based resources. Failures are never cached. */
class ResourceResolver(
    private val backend: ResourceBackend,
) {
    private val strings = LruCache<String, String>(CACHE_ENTRIES)
    private val images =
        object : LruCache<String, Painter>(MAX_IMAGE_BYTES) {
            override fun sizeOf(
                key: String,
                value: Painter,
            ): Int {
                val size = value.intrinsicSize
                if (!size.isSpecified || !size.width.isFinite() || !size.height.isFinite()) return 1
                return (size.width * size.height * BYTES_PER_PIXEL).toInt().coerceAtLeast(1)
            }
        }
    private val fonts = LruCache<String, FontFamily>(CACHE_ENTRIES)

    fun string(
        key: String,
        locale: String? = null,
    ): Result<String> =
        runCatching {
            name("string", key)
            require(locale == null || LOCALE.matches(locale)) { "Invalid locale: $locale" }
            val cacheKey = "$key:$locale"
            strings[cacheKey] ?: backend.string(key, locale).also { strings.put(cacheKey, it) }
        }

    fun drawable(key: String): Result<Painter> =
        runCatching {
            name("drawable", key)
            val cacheKey = "drawable:$key"
            images[cacheKey] ?: backend.drawable(key).also { images.put(cacheKey, it) }
        }

    /** Binary I/O: callers must run this and image/font decoding off the Compose thread. */
    fun asset(key: String): Result<ByteArray> =
        runCatching {
            name("asset", key)
            backend.asset(key)
        }

    fun font(key: String): Result<FontFamily> =
        runCatching {
            name("font", key)
            fonts[key] ?: backend.font(key).also { fonts.put(key, it) }
        }

    fun image(reference: String): Result<Painter> =
        runCatching {
            val resource = ResourceReference.parse(reference, IMAGE_KINDS).getOrThrow()
            if (resource.kind == "drawable") {
                return@runCatching drawable(resource.name).getOrThrow()
            }
            images[reference] ?: when (resource.kind) {
                "file" -> backend.fileImage(resource.name)
                else -> backend.assetImage(resource.name)
            }.also { images.put(reference, it) }
        }

    fun invalidate() {
        strings.evictAll()
        images.evictAll()
        fonts.evictAll()
    }

    private fun name(
        kind: String,
        value: String,
    ) {
        ResourceReference.parse("@$kind/$value", setOf(kind)).getOrThrow()
    }

    companion object {
        private const val CACHE_ENTRIES = 16
        private const val MAX_IMAGE_BYTES = 16 * 1024 * 1024
        private const val BYTES_PER_PIXEL = 4
        private val IMAGE_KINDS = setOf("drawable", "asset", "file")
        private val LOCALE = Regex("[a-z]{2,3}(?:-[A-Z][a-z]{3})?(?:-(?:[A-Z]{2}|[0-9]{3}))?")
    }
}
