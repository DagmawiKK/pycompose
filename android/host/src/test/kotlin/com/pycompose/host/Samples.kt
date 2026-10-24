package com.pycompose.host

import java.io.File

/**
 * The render gate's samples, written from the lock by `tools/previews.py`.
 *
 * They are the lock's output, so they are not committed: the first test that
 * asks writes them into `build/previews`, once per test JVM. The Python is
 * `PYCOMPOSE_PYTHON`, else the repository's `.venv`, else `python3`, with the
 * package's dependencies installed.
 */
internal object Samples {
    val directory: File by lazy {
        val root = File("../..").canonicalFile
        val out = File("build/previews").canonicalFile
        val python =
            System.getenv("PYCOMPOSE_PYTHON")
                ?: File(root, ".venv/bin/python").takeIf { it.isFile }?.path
                ?: "python3"
        val process =
            ProcessBuilder(python, "tools/previews.py", "--out", out.path)
                .directory(root)
                .redirectErrorStream(true)
                .start()
        val output = process.inputStream.bufferedReader().readText()
        check(process.waitFor() == 0) { "tools/previews.py failed:\n$output" }
        out
    }

    /** The components with a sample, in catalog order. */
    fun names(): List<String> = File(directory, "index.txt").readLines().filter { it.isNotBlank() }

    /** One component's sample snapshot. */
    fun source(component: String): String = File(directory, "$component.json").readText()
}
