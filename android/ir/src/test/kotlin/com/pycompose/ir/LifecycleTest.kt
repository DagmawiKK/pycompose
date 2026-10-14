package com.pycompose.ir

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import org.junit.jupiter.params.ParameterizedTest
import org.junit.jupiter.params.provider.ValueSource

class LifecycleTest {
    private val validConfig =
        Lifecycle.payload("landscape", true, "fr-FR", 3.0)

    @Test
    fun `declared events are exactly the ones the host emits`() {
        assertEquals(
            setOf(
                "onResume",
                "onPause",
                "onBackRequested",
                "onConfigChanged",
                "onRouteChanged",
            ),
            Lifecycle.ids,
        )
    }

    @Test
    fun `a route change carries the destination Python should render`() {
        val payload = Lifecycle.route("note:5")
        Lifecycle.check("onRouteChanged", payload)
        assertEquals("note:5", payload["route"].toString().trim('"'))
    }

    // An empty route is a legal string, and a blank destination is already
    // rejected in navigate() before it can reach this contract.
    @ParameterizedTest
    @ValueSource(
        strings = ["""{"route":7}""", """{}""", """{"route":"a","x":1}"""],
    )
    fun `a route change outside the contract fails closed`(payload: String) {
        val value =
            kotlinx.serialization.json.Json
                .parseToJsonElement(payload)
        val failure =
            runCatching {
                Lifecycle.check(
                    "onRouteChanged",
                    value as kotlinx.serialization.json.JsonObject,
                )
            }
        assertTrue(failure.isFailure, payload)
    }

    @Test
    fun `a configuration payload carries only facts Python cannot observe`() {
        Lifecycle.check("onConfigChanged", validConfig)
        assertEquals("landscape", validConfig["orientation"].toString().trim('"'))
        assertEquals(true, validConfig["darkMode"].toString().toBoolean())
        assertEquals("fr-FR", validConfig["locale"].toString().trim('"'))
    }

    @Test
    fun `empty payloads are legal for events that carry nothing`() {
        Lifecycle.check("onResume", kotlinx.serialization.json.JsonObject(emptyMap()))
        Lifecycle.check("onPause", kotlinx.serialization.json.JsonObject(emptyMap()))
        Lifecycle.check("onBackRequested", kotlinx.serialization.json.JsonObject(emptyMap()))
    }

    @Test
    fun `orientation is reported as one of two values`() {
        assertEquals("portrait", Lifecycle.orientation(false))
        assertEquals("landscape", Lifecycle.orientation(true))
    }

    @ParameterizedTest
    @ValueSource(strings = ["onCreate", "onDestroy", "resume", ""])
    fun `an undeclared lifecycle event is rejected`(event: String) {
        val failure =
            runCatching {
                Lifecycle.check(event, kotlinx.serialization.json.JsonObject(emptyMap()))
            }
        assertTrue(failure.isFailure, event)
    }

    @ParameterizedTest
    @ValueSource(
        strings = [
            """{"orientation":"sideways","darkMode":false,"locale":"en","density":2.0}""",
            """{"orientation":"portrait","darkMode":"yes","locale":"en","density":2.0}""",
            """{"orientation":"portrait","darkMode":false,"locale":1,"density":2.0}""",
            """{"orientation":"portrait","darkMode":false,"locale":"en"}""",
            """{"orientation":"portrait","darkMode":false,"locale":"en","density":2.0,"x":1}""",
        ],
    )
    fun `a configuration payload outside the contract fails closed`(payload: String) {
        val value =
            kotlinx.serialization.json.Json
                .parseToJsonElement(payload)
        val failure =
            runCatching {
                Lifecycle.check(
                    "onConfigChanged",
                    value as kotlinx.serialization.json.JsonObject,
                )
            }
        assertTrue(failure.isFailure, payload)
    }

    @Test
    fun `a lifecycle event is not a legal action id for a component`() {
        // Lifecycle ids live outside IrContract.actionIds, so no control may bind one.
        assertTrue(Lifecycle.ids.none { it in com.pycompose.ir.generated.IrContract.actionIds })
    }
}
