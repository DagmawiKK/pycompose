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

    fun reload(
        route: String,
        restore: String = "",
    )
}
