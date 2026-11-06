package com.pycompose.host.ui

import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.ColorScheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.lightColorScheme
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.unit.dp
import com.pycompose.renderer.generated.ValueResolver
import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** The theme's families: what the app states, the rest as the factory itself would make it. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34], application = android.app.Application::class)
class ThemeFamiliesTest {
    @get:Rule val compose = createComposeRule()

    @Test
    fun aStatedPrimaryTintsTheSurfaceAndTheRestComeFromTheBareFactory() {
        // lightColorScheme defaults surfaceTint to primary and every other role to an
        // internal token: the stated primary carries, the tokens are read back from the
        // factory called bare.
        lateinit var scheme: ColorScheme
        compose.setContent {
            scheme =
                ValueResolver
                    .colorScheme(
                        Json.parseToJsonElement(
                            """{"type":"LightColorScheme",
                              "primary":{"type":"Color","color":4294901760}}""",
                        ),
                    ).getOrThrow()
        }
        compose.waitForIdle()

        val bare = lightColorScheme()
        assertEquals(Color.Red, scheme.primary)
        assertEquals(Color.Red, scheme.surfaceTint)
        assertEquals(bare.onPrimary, scheme.onPrimary)
        assertEquals(bare.background, scheme.background)
    }

    @Test
    fun shapesTakeTheStatedCornersAndKeepTheirDefaults() {
        lateinit var shapes: Shapes
        compose.setContent {
            shapes =
                ValueResolver
                    .shapes(
                        Json.parseToJsonElement(
                            """{"type":"Shapes",
                              "small":{"type":"RoundedCorners","size":{"type":"Dp","value":8}}}""",
                        ),
                    ).getOrThrow()
        }
        compose.waitForIdle()

        assertEquals(RoundedCornerShape(8.dp), shapes.small)
        assertEquals(Shapes().large, shapes.large)
    }
}
