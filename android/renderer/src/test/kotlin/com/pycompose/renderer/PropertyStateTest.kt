package com.pycompose.renderer

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.test.junit4.createComposeRule
import com.pycompose.ir.AppBinding
import com.pycompose.ir.OptionalValue
import com.pycompose.ir.PropertyRule
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.long
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** A holder property the pin derives a family for, reconciled like any family's value. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class PropertyStateTest {
    @get:Rule val compose = createComposeRule()

    private class Holder {
        var hour by mutableIntStateOf(0)
    }

    @Test
    fun aStatedValueIsWrittenAndASettledOneIsReported() {
        val actions = mutableListOf<Action>()
        val dispatcher = ActionDispatcher { actions.add(it) }
        val binding =
            AppBinding(
                payload = mapOf("hour" to PropertyRule("integer", required = true)),
                bound = JsonObject(emptyMap()),
            )
        val renderer = Renderer(ComponentRegistry.Builder().build(), dispatcher)
        val context = RenderContext(dispatcher, renderer, mapOf("app.hour.1" to binding))
        val holder = Holder()
        var desired by mutableStateOf<Wanted<Int>?>(Wanted(9))
        compose.setContent {
            context.reconcileProperty(
                holder,
                "hour",
                desired,
                "app.hour.1",
                { holder.hour },
                { holder.hour = it },
            ) { JsonPrimitive(it) }
        }
        compose.waitForIdle()
        assertEquals(9, holder.hour)

        // The user picks a time: the app hears the settled value.
        holder.hour = 5
        compose.waitForIdle()
        assertEquals(JsonPrimitive(5), actions.last().payload["hour"])

        // Stating nothing leaves the user's value alone.
        desired = null
        compose.waitForIdle()
        assertEquals(5, holder.hour)
    }

    @Test
    fun anOptionalNullablePropStatesNothingClearsOrSets() {
        assertEquals(null, OptionalValue.Absent.wanted { it.long })
        assertEquals(Wanted(null), OptionalValue.Null.wanted { it.long })
        assertEquals(Wanted(7L), OptionalValue.Present(JsonPrimitive(7)).wanted { it.long })
        assertEquals(JsonNull, JsonPrimitive(null as Long?))
    }
}
