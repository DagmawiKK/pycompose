package com.pycompose.host.resources

import android.annotation.SuppressLint
import android.content.Context
import android.content.res.Configuration
import android.graphics.BitmapFactory
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.painter.BitmapPainter
import androidx.compose.ui.graphics.painter.Painter
import androidx.compose.ui.text.font.FontFamily
import androidx.core.content.res.ResourcesCompat
import androidx.core.graphics.drawable.toBitmap
import java.io.ByteArrayOutputStream
import java.io.File
import java.util.Locale

/** The only name-to-Android-id implementation. No reflection or generated R coupling. */
class AndroidResources(
    context: Context,
) : ResourceBackend {
    private val context = context.applicationContext

    override fun string(
        name: String,
        locale: String?,
    ): String {
        val localized =
            if (locale == null) {
                context
            } else {
                val configuration = Configuration(context.resources.configuration)
                configuration.setLocale(Locale.forLanguageTag(locale))
                context.createConfigurationContext(configuration)
            }
        return localized.getString(identifier(name, "string"))
    }

    override fun drawable(name: String): Painter {
        val id = identifier(name, "drawable")
        val drawable =
            checkNotNull(
                ResourcesCompat.getDrawable(context.resources, id, context.theme),
            )
        val width = drawable.intrinsicWidth.coerceAtLeast(1)
        val height = drawable.intrinsicHeight.coerceAtLeast(1)
        require(width.toLong() * height <= MAX_PIXELS) { "Drawable is too large" }
        return BitmapPainter(drawable.toBitmap(width, height).asImageBitmap())
    }

    override fun asset(name: String): ByteArray =
        context.assets.open(name).use { stream ->
            val output = ByteArrayOutputStream()
            val buffer = ByteArray(BUFFER_BYTES)
            var read = stream.read(buffer)
            while (read != -1) {
                require(output.size() + read <= MAX_ASSET_BYTES) { "Asset is too large" }
                output.write(buffer, 0, read)
                read = stream.read(buffer)
            }
            output.toByteArray()
        }

    override fun assetImage(name: String): Painter = decodeImage(asset(name))

    override fun fileImage(name: String): Painter {
        val file = File(File(context.cacheDir, MEDIA), name)
        require(file.length() in 1..MAX_ASSET_BYTES) { "Media file is missing or too large" }
        return decodeImage(file.readBytes())
    }

    private fun decodeImage(bytes: ByteArray): Painter {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeByteArray(bytes, 0, bytes.size, bounds)
        require(bounds.outWidth > 0 && bounds.outHeight > 0) { "Invalid image" }
        val area = bounds.outWidth.toLong() * bounds.outHeight
        require(area <= MAX_PIXELS) { "Image is too large" }
        val bitmap = checkNotNull(BitmapFactory.decodeByteArray(bytes, 0, bytes.size))
        return BitmapPainter(bitmap.asImageBitmap())
    }

    override fun font(name: String): FontFamily =
        FontFamily(
            checkNotNull(ResourcesCompat.getFont(context, identifier(name, "font"))),
        )

    @SuppressLint("DiscouragedApi") // Resources are an explicitly name-based public contract.
    private fun identifier(name: String, kind: String): Int {
        val id = context.resources.getIdentifier(name, kind, context.packageName)
        require(id != 0) { "Missing @$kind/$name" }
        return id
    }

    companion object {
        /** The cache folder Python writes media into (`pycompose.media`). */
        private const val MEDIA = "pycompose-media"
        private const val MAX_ASSET_BYTES = 8 * 1024 * 1024
        private const val MAX_PIXELS = 4L * 1024 * 1024
        private const val BUFFER_BYTES = 8192
    }
}
