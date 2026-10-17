package com.pycompose.host.bridge

/** Synchronous data-only seam. Every method is invoked on the single worker. */
interface BridgeSurface {
    fun start(
        route: String,
        restore: String = "",
    )

    fun acceptAction(action: String)

    fun fetchLatestSnapshot(): String

    fun fetchLatestError(): String

    /** True only when a new valid Python session replaced the previous one. */
    fun reload(
        route: String,
        restore: String = "",
    ): Boolean
}
