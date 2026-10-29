package com.pycompose.host

import android.net.Uri
import android.util.Log
import android.webkit.MimeTypeMap
import androidx.activity.ComponentActivity
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.io.File
import java.io.InputStream
import java.io.OutputStream
import java.security.MessageDigest

/**
 * The system pickers, registered once per activity, answering `pickFile` effects.
 *
 * A request for images opens the photo picker, any other the document picker; neither
 * needs a permission. The pick is copied into the app's media cache, named by its
 * content's SHA-256, and Python receives the copy's path: bytes never cross the
 * bridge. The request is kept in the model's saved state, so an answer that
 * reaches an activity recreated meanwhile still names it.
 */
internal class FilePicker(
    private val activity: ComponentActivity,
    private val model: PyComposeViewModel,
) {
    private val photos =
        activity.registerForActivityResult(ActivityResultContracts.PickVisualMedia(), ::picked)
    private val documents =
        activity.registerForActivityResult(ActivityResultContracts.OpenDocument(), ::picked)

    fun pick(
        request: String,
        accept: String,
    ) {
        model.pickRequest = request
        if (accept == IMAGES) {
            photos.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly))
        } else {
            documents.launch(arrayOf(accept))
        }
    }

    private fun picked(uri: Uri?) {
        val request = model.pickRequest ?: return
        model.pickRequest = null
        activity.lifecycleScope.launch {
            // An empty path is a cancelled pick, or one that could not be copied.
            val path =
                uri?.let {
                    withContext(Dispatchers.IO) {
                        runCatching { copy(it) }
                            .onFailure { Log.w("PyCompose", "Picked file could not be copied", it) }
                            .getOrNull()
                    }
                } ?: ""
            val answer = mapOf("request" to JsonPrimitive(request), "path" to JsonPrimitive(path))
            model.lifecycle("onFilePicked", JsonObject(answer))
        }
    }

    /** Copy [uri] into the media cache under its digest, hashing as it streams. */
    private fun copy(uri: Uri): String {
        val folder = File(activity.cacheDir, MEDIA).apply { mkdirs() }
        val partial = File.createTempFile("pick", ".partial", folder)
        val digest = MessageDigest.getInstance("SHA-256")
        try {
            val input =
                checkNotNull(activity.contentResolver.openInputStream(uri)) { "Unreadable pick" }
            input.use { stream ->
                partial.outputStream().use { out -> hashed(stream, out, digest) }
            }
            val type = activity.contentResolver.getType(uri)
            val extension =
                type?.let { MimeTypeMap.getSingleton().getExtensionFromMimeType(it) } ?: "bin"
            val name = digest.digest().joinToString("") { "%02x".format(it) } + ".$extension"
            val target = File(folder, name)
            if (!partial.renameTo(
                    target,
                )
            ) {
                check(target.exists()) { "Picked file could not be kept" }
            }
            return target.absolutePath
        } finally {
            partial.delete()
        }
    }

    /** Copy [input] to [out], feeding [digest], refusing more than [MAX_BYTES]. */
    private fun hashed(
        input: InputStream,
        out: OutputStream,
        digest: MessageDigest,
    ) {
        val buffer = ByteArray(BUFFER_BYTES)
        var total = 0L
        var read = input.read(buffer)
        while (read >= 0) {
            total += read
            require(total <= MAX_BYTES) { "Picked file is too large" }
            digest.update(buffer, 0, read)
            out.write(buffer, 0, read)
            read = input.read(buffer)
        }
    }

    private companion object {
        const val IMAGES = "image/*"
        const val MEDIA = "pycompose-media"
        const val BUFFER_BYTES = 64 * 1024
        const val MAX_BYTES = 64L * 1024 * 1024
    }
}
