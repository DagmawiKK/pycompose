package com.pycompose.host

import com.pycompose.renderer.Action
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34], application = android.app.Application::class)
class CoalesceTest {
    private fun report(
        value: String,
        seq: Long,
    ) = Queued(
        Command.Dispatch(
            Action("app.query", JsonObject(mapOf("value" to JsonPrimitive(value))), seq = seq),
        ),
        cookie = 0,
    )

    private fun tap() = Queued(Command.Dispatch(Action("app.search")), cookie = 0)

    private fun values(batch: List<Queued>) =
        batch.map {
            val action = (it.command as Command.Dispatch).action
            action.payload["value"]?.toString() ?: action.actionId
        }

    @Test
    fun adjacentReportsCollapseToTheNewest() {
        val batch = listOf(report("a", 1), report("ab", 2), report("abc", 3))
        assertEquals(listOf("\"abc\""), values(coalesce(batch)))
    }

    @Test
    fun aReportBeforeAnIntentIsKeptForThatIntent() {
        val batch = listOf(report("a", 1), tap(), report("ab", 2))
        assertEquals(listOf("\"a\"", "app.search", "\"ab\""), values(coalesce(batch)))
    }

    @Test
    fun eachRunBetweenIntentsKeepsItsNewestReport() {
        val batch = listOf(report("a", 1), report("ab", 2), tap(), report("x", 3), report("xy", 4))
        assertEquals(listOf("\"ab\"", "app.search", "\"xy\""), values(coalesce(batch)))
    }

    @Test
    fun windowRequestsCollapseOnlyBetweenOtherCommands() {
        val batch =
            listOf(
                Queued(Command.Window("list", 0, 10), cookie = 0),
                Queued(Command.Window("list", 5, 15), cookie = 0),
                tap(),
                Queued(Command.Window("list", 20, 30), cookie = 0),
            )
        val kept = coalesce(batch).map { it.command }
        assertEquals(
            listOf(
                Command.Window("list", 5, 15),
                Command.Dispatch(Action("app.search")),
                Command.Window("list", 20, 30),
            ),
            kept,
        )
    }
}
