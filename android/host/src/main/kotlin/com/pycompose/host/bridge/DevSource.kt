package com.pycompose.host.bridge

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import java.io.File
import java.net.HttpURLConnection
import java.net.URI
import kotlin.io.encoding.Base64

/**
 * An app served by `pycompose run --dev-client`: the dev
 * server's bundle, kept in the host's private files.
 *
 * A debug build launched with a dev URL runs the app it serves instead of the
 * one it was built with. Each pull asks the dev server for its bundle and,
 * when the revision moved, writes the app's files under [root] -- only there,
 * removing files the app no longer has. The bridge then imports the app from
 * [source].
 *
 * @param url The dev server, reached over `adb reverse`.
 * @param token The dev server's bearer token.
 * @param sourceDir The app's Python directory within the bundle (`python.source_dir`).
 * @param root Where the bundle is written.
 */
class DevSource(
    private val url: String,
    private val token: String,
    sourceDir: String,
    private val root: File,
) {
    /** The app's Python directory, which the bridge puts first on Python's path. */
    val source: File = File(root, sourceDir)

    private var revision = -1L
    private var written = emptySet<String>()

    /**
     * Fetch the bundle and write it if it changed.
     *
     * @return True when new files were written.
     */
    fun pull(): Boolean {
        val connection = URI("$url/session").toURL().openConnection() as HttpURLConnection
        connection.setRequestProperty("Authorization", "Bearer $token")
        connection.connectTimeout = TIMEOUT_MS
        connection.readTimeout = TIMEOUT_MS
        val body =
            try {
                check(connection.responseCode == HttpURLConnection.HTTP_OK) {
                    "Dev server answered ${connection.responseCode}"
                }
                connection.inputStream.use { it.readBytes().decodeToString() }
            } finally {
                connection.disconnect()
            }
        return apply(Json.parseToJsonElement(body).jsonObject)
    }

    /**
     * Write one bundle if its revision is new.
     *
     * @param bundle The dev server's `/session` document.
     * @return True when new files were written.
     */
    fun apply(bundle: JsonObject): Boolean {
        val next = bundle.getValue("revision").jsonPrimitive.long
        if (next == revision) return false
        val files = bundle.getValue("files").jsonObject
        val base = root.canonicalFile
        files.forEach { (name, content) ->
            val target = File(base, name).canonicalFile
            check(target.path.startsWith(base.path + File.separator)) {
                "Bundle path escapes: $name"
            }
            target.parentFile.mkdirs()
            target.writeBytes(Base64.decode(content.jsonPrimitive.content))
        }
        (written - files.keys).forEach { File(base, it).delete() }
        written = files.keys
        revision = next
        return true
    }

    private companion object {
        const val TIMEOUT_MS = 5_000
    }
}
