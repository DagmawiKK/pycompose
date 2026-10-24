package com.pycompose.host

import com.pycompose.host.bridge.DevSource
import com.sun.net.httpserver.HttpServer
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import org.junit.jupiter.api.io.TempDir
import java.io.File
import java.net.InetSocketAddress
import java.util.Base64

/** A dev client keeps the app its dev server serves (plan 31 §18.8). */
class DevSourceTest {
    @TempDir lateinit var root: File

    private fun bundle(
        revision: Int,
        vararg files: Pair<String, String>,
    ) = Json
        .parseToJsonElement(
            """{"revision":$revision,"files":{${
                files.joinToString(",") { (name, text) ->
                    "\"$name\":\"${Base64.getEncoder().encodeToString(text.toByteArray())}\""
                }
            }}}""",
        ).jsonObject

    @Test
    fun `a new revision is written, an unchanged one is not, and stale files go`() {
        val dev = DevSource("http://unused", "token", "app", root)
        assertTrue(dev.apply(bundle(1, "app/main.py" to "a = 1", "app/old.py" to "")))
        assertEquals("a = 1", File(dev.source, "main.py").readText())
        assertFalse(dev.apply(bundle(1, "app/main.py" to "a = 2")))
        assertTrue(dev.apply(bundle(2, "app/main.py" to "a = 2")))
        assertEquals("a = 2", File(dev.source, "main.py").readText())
        assertFalse(File(dev.source, "old.py").exists())
    }

    @Test
    fun `a bundle path escaping the directory is refused`() {
        val dev = DevSource("http://unused", "token", "app", root)
        assertThrows<IllegalStateException> { dev.apply(bundle(1, "../outside.py" to "")) }
        assertFalse(File(root.parentFile, "outside.py").exists())
    }

    @Test
    fun `the bundle is pulled from the dev server with its token`() {
        val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        server.createContext("/session") { exchange ->
            val authorized = exchange.requestHeaders.getFirst("Authorization") == "Bearer secret"
            val body = bundle(7, "app/main.py" to "served").toString().toByteArray()
            exchange.sendResponseHeaders(
                if (authorized) 200 else 401,
                if (authorized) body.size.toLong() else -1,
            )
            if (authorized) exchange.responseBody.use { it.write(body) } else exchange.close()
        }
        server.start()
        try {
            val url = "http://127.0.0.1:${server.address.port}"
            val dev = DevSource(url, "secret", "app", root)
            assertTrue(dev.pull())
            assertEquals("served", File(dev.source, "main.py").readText())
            assertThrows<IllegalStateException> { DevSource(url, "wrong", "app", root).pull() }
        } finally {
            server.stop(0)
        }
    }
}
