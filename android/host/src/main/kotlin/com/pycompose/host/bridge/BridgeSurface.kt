package com.pycompose.host.bridge

/** Synchronous data-only seam. Every method is invoked on the single worker. */
interface BridgeSurface {
    fun start(
        route: String,
        restore: String = "",
    )

    fun acceptAction(action: String)

    fun fetchLatestSnapshot(): String

    /**
     * The latest snapshot of [surface] as a patch against [baseSerial], or whole (ADR-0018).
     *
     * A bridge without a serial window answers with the bare snapshot, which the
     * host accepts as a whole one.
     */
    fun fetchLatest(
        surface: String,
        baseSerial: Long,
    ): String = fetchLatestSnapshot()

    /**
     * Ask the app to compose items [first] to [last] of the lazy list keyed [key] on
     * [surface]. A bridge without windowing composes every item and needs nothing.
     */
    fun requestWindow(
        surface: String,
        key: String,
        first: Int,
        last: Int,
    ) = Unit

    fun fetchLatestError(): String

    /** True only when a new valid Python session replaced the previous one. */
    fun reload(
        route: String,
        restore: String = "",
    ): Boolean

    /** Worker-owned teardown. Implementations without owned resources need no hook. */
    fun close() {}
}
