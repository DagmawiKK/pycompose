package com.pycompose.host

import com.pycompose.host.bridge.BridgeSurface

/** A worker that answers with the counter golden, recording what the host asked of it. */
internal class FakeBridge : BridgeSurface {
    var reloadSucceeded = true
    val calls = mutableListOf<String>()
    val starts = mutableListOf<Start>()

    /** Every action envelope this bridge was asked to deliver to Python. */
    val sent = mutableListOf<String>()
    private var accepted = 0
    private var valid = true

    data class Start(
        val route: String,
        val restore: String,
    )

    /** Effects the worker attaches to every snapshot it hands back. */
    var pendingEffects = """[{"kind":"toast","payload":{"message":"saved"}}]"""

    /** App data the worker publishes, or null for an app that holds none. */
    var pendingData: String? = null

    /** The serial every pulled snapshot is published under, or null for bare snapshots. */
    var serial: Long? = null

    override fun start(
        route: String,
        restore: String,
    ) {
        starts.add(Start(route, restore))
        calls.add("start:$route")
    }

    override fun acceptAction(action: String) {
        accepted++
        sent.add(action)
        calls.add("action:$accepted")
        // The worker goes silent after the first action, so the host must
        // keep rendering the last good snapshot.
        if (accepted > 1) valid = false
    }

    override fun fetchLatestSnapshot(): String {
        calls.add("pull")
        if (!valid) return "{}"
        val golden = checkNotNull(javaClass.getResource("/ir_counter.json")).readText()
        val data = pendingData
        val metadata =
            if (data == null) {
                """{"effects":$pendingEffects}"""
            } else {
                """{"effects":$pendingEffects,"data":$data}"""
            }
        return golden
            .replace("\"schemaVersion\":\"1.0.0\"", "\"schemaVersion\":\"1.4.0\"")
            .replace("{\"root\"", "{\"metadata\":$metadata,\"root\"")
    }

    override fun fetchLatest(
        surface: String,
        baseSerial: Long,
    ): String {
        val snapshot = fetchLatestSnapshot()
        val published = serial ?: return snapshot
        return snapshot.replaceFirst("{", "{\"kind\":\"full\",\"serial\":$published,")
    }

    override fun fetchLatestError(): String = ""

    override fun reload(
        route: String,
        restore: String,
    ): Boolean {
        calls.add("reload:$route")
        return reloadSucceeded
    }
}
