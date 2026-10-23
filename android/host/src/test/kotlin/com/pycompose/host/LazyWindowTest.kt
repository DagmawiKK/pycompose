package com.pycompose.host

import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.hasScrollToIndexAction
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performScrollToIndex
import com.pycompose.host.ui.BuiltinComponents
import com.pycompose.host.ui.PyComposeTheme
import com.pycompose.ir.IrParser
import com.pycompose.renderer.ActionDispatcher
import com.pycompose.renderer.Renderer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** A list of ten thousand renders its window and asks for the next as the user scrolls. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class LazyWindowTest {
    @get:Rule val compose = createComposeRule()

    private fun window(offset: Int) =
        IrParser()
            .parse(
                """{"version":"0.1.0","schemaVersion":"1.23.0","root":{"id":"list",
                "type":"LazyColumn","props":{"itemCount":10000,"itemOffset":$offset,
                "window":"/list"},"children":[${
                    (offset until offset + 40).joinToString(",") {
                        """{"id":"n$it","type":"Text","props":{"text":"row $it"}}"""
                    }
                }]}}""",
            ).getOrThrow()

    @Test
    fun scrollingPastTheWindowAsksForTheOneAroundWhereTheUserLands() {
        val ir = mutableStateOf(window(0))
        val requests = mutableListOf<Triple<String, Int, Int>>()
        val renderer =
            Renderer(
                BuiltinComponents.registry(),
                ActionDispatcher {},
                windows = { key, first, last -> requests += Triple(key, first, last) },
            )
        compose.setContent { PyComposeTheme { renderer.Render(ir.value) } }
        compose.onNodeWithText("row 0").assertExists()

        compose.onNode(hasScrollToIndexAction()).performScrollToIndex(5000)
        compose.waitUntil(5000) { requests.isNotEmpty() }

        val (key, first, last) = requests.last()
        assertEquals("/list", key)
        assertTrue("$first..$last covers 5000", first <= 5000 && last >= 5000)
        compose.runOnIdle { ir.value = window(first) }
        compose.onNodeWithText("row 5000").assertExists()
    }
}
