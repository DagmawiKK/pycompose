package com.pycompose.host.ui

import androidx.compose.foundation.layout.Box
import androidx.compose.material3.ButtonColors
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ButtonElevation
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Canvas
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.graphics.drawOutline
import androidx.compose.ui.graphics.drawscope.CanvasDrawScope
import androidx.compose.ui.graphics.toPixelMap
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.test.assertHeightIsEqualTo
import androidx.compose.ui.test.assertWidthIsEqualTo
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performSemanticsAction
import androidx.compose.ui.text.TextLayoutResult
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.em
import androidx.compose.ui.unit.sp
import com.pycompose.ir.IrParser
import com.pycompose.renderer.ActionDispatcher
import com.pycompose.renderer.Renderer
import com.pycompose.renderer.generated.ValueResolver
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34], application = android.app.Application::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class ValueRenderingTest {
    @get:Rule val compose = createComposeRule()

    @Test fun taggedColorReachesNativeText() {
        val source = """{
            "version":"0.1.0","schemaVersion":"1.11.0",
            "root":{"id":"root","type":"Text","props":{
                "text":"Typed value","color":{"type":"Color","color":4281558681}
            }}
        }"""
        val snapshot = IrParser().parse(source).getOrThrow()
        compose.setContent {
            PyComposeTheme {
                Renderer(BuiltinComponents.registry(), ActionDispatcher {}).Render(snapshot)
            }
        }
        val results = mutableListOf<TextLayoutResult>()
        compose
            .onNodeWithText("Typed value")
            .performSemanticsAction(SemanticsActions.GetTextLayoutResult) { it(results) }
        assertEquals(
            Color(0xFF336699),
            results
                .single()
                .layoutInput.style.color,
        )
    }

    @Test fun textUnitsAndNullableFontReachNativeText() {
        val source = """{
            "version":"0.1.0","schemaVersion":"1.11.0",
            "root":{"id":"root","type":"Text","props":{
                "text":"Styled value","style":{"type":"TextStyle",
                    "fontSize":{"type":"Sp","value":22},
                    "letterSpacing":{"type":"Em","value":0.1},"fontFamily":null}
            }}
        }"""
        val snapshot = IrParser().parse(source).getOrThrow()
        compose.setContent {
            PyComposeTheme {
                Renderer(
                    BuiltinComponents.registry(),
                    ActionDispatcher {},
                ).Render(snapshot)
            }
        }
        val results = mutableListOf<TextLayoutResult>()
        compose
            .onNodeWithText("Styled value")
            .performSemanticsAction(SemanticsActions.GetTextLayoutResult) { it(results) }
        assertEquals(
            22.sp,
            results
                .single()
                .layoutInput.style.fontSize,
        )
        assertEquals(
            0.1.em,
            results
                .single()
                .layoutInput.style.letterSpacing,
        )
    }

    @Test fun edgesShapeAndGradientRenderThroughIr() {
        val source = """{
            "version":"0.1.0","schemaVersion":"1.11.0",
            "root":{"id":"root","type":"Text","props":{
              "text":" ","modifier":{"operations":[
                {"type":"size","width":{"type":"Dp","value":80},"height":{"type":"Dp","value":40}},
                {"type":"clip","shape":{"type":"RoundedCornerShape","size":{"type":"Dp","value":8}}},
                {"type":"background","brush":{"type":"horizontalGradient","colors":[
                  {"type":"Color","color":4294901760},{"type":"Color","color":4278190335}]}}
              ]}
            }}
        }"""
        val snapshot = IrParser().parse(source).getOrThrow()
        val program =
            Json
                .parseToJsonElement(source)
                .jsonObject
                .getValue("root")
                .jsonObject
                .getValue(
                    "props",
                ).jsonObject
                .getValue("modifier")
                .jsonObject
                .getValue("operations")
                .jsonArray
        lateinit var brush: Brush
        lateinit var shape: Shape
        compose.setContent {
            PyComposeTheme {
                brush = ValueResolver.brush(program[2].jsonObject.getValue("brush")).getOrThrow()
                shape = ValueResolver.shape(program[1].jsonObject.getValue("shape")).getOrThrow()
                Renderer(BuiltinComponents.registry(), ActionDispatcher {}).Render(snapshot)
            }
        }
        compose.onNodeWithText(" ").assertWidthIsEqualTo(80.dp).assertHeightIsEqualTo(40.dp)
        val image = ImageBitmap(80, 40)
        val density = Density(1f)
        CanvasDrawScope().draw(density, LayoutDirection.Ltr, Canvas(image), Size(80f, 40f)) {
            drawOutline(shape.createOutline(size, LayoutDirection.Ltr, density), brush)
        }
        val pixels = image.toPixelMap()
        assertTrue(pixels[2, pixels.height / 2].red > 0.8f)
        assertTrue(pixels[pixels.width - 3, pixels.height / 2].blue > 0.8f)
        assertTrue(pixels[0, 0].alpha < 0.1f)
    }

    @Test fun themeReferencesAndFactoriesFollowRecomposition() {
        val primary = mutableStateOf(Color.Red)
        val source = """{"version":"0.1.0","schemaVersion":"1.11.0","root":{
            "id":"root","type":"Button","props":{"text":"Factory","onClick":"increment",
              "colors":{"type":"buttonColors"},"elevation":null}
        }}"""
        val snapshot = IrParser().parse(source).getOrThrow()
        lateinit var colors: ButtonColors
        lateinit var elevation: ButtonElevation
        lateinit var expectedElevation: ButtonElevation
        compose.setContent {
            MaterialTheme(colorScheme = lightColorScheme(primary = primary.value)) {
                colors =
                    ValueResolver
                        .buttonColors(
                            Json.parseToJsonElement("""{"type":"buttonColors"}"""),
                        ).getOrThrow()
                elevation =
                    ValueResolver
                        .buttonElevation(
                            Json.parseToJsonElement("""{"type":"buttonElevation"}"""),
                        ).getOrThrow()
                expectedElevation = ButtonDefaults.buttonElevation()
                val style =
                    ValueResolver
                        .textStyle(
                            Json.parseToJsonElement(
                                """{"type":"TextStyle",
                    "color":{"type":"ThemeColor","name":"primary"},"fontSize":{"type":"Sp","value":20},
                    "fontFamily":{"type":"FontFamily","name":"Monospace"},"fontWeight":{"type":"FontWeight","weight":700}}
                """,
                            ),
                        ).getOrThrow()
                androidx.compose.material3.Text("Theme reference", style = style)
                Renderer(BuiltinComponents.registry(), ActionDispatcher {}).Render(snapshot)
            }
        }

        fun layout(): TextLayoutResult {
            val results = mutableListOf<TextLayoutResult>()
            compose
                .onNodeWithText(
                    "Theme reference",
                ).performSemanticsAction(SemanticsActions.GetTextLayoutResult) {
                    it(results)
                }
            return results.single()
        }
        assertEquals(Color.Red, layout().layoutInput.style.color)
        assertEquals(FontFamily.Monospace, layout().layoutInput.style.fontFamily)
        assertEquals(FontWeight.Bold, layout().layoutInput.style.fontWeight)
        assertEquals(Color.Red, colors.containerColor)
        assertEquals(expectedElevation, elevation)
        compose.runOnIdle { primary.value = Color.Blue }
        assertEquals(Color.Blue, layout().layoutInput.style.color)
        assertEquals(Color.Blue, colors.containerColor)
    }

    @Test fun paddingAndInsetsAffectMeasuredNativeContent() {
        val source = """{"version":"0.1.0","schemaVersion":"1.11.0","root":{
            "id":"root","type":"Text","props":{"text":"Edges","modifier":{"operations":[
              {"type":"padding","value":{"type":"PaddingValues","start":{"type":"Dp","value":4},"top":{"type":"Dp","value":6}}},
              {"type":"windowInsetsPadding","insets":{"type":"WindowInsets","left":{"type":"Dp","value":3},"top":{"type":"Dp","value":5}}},
              {"type":"size","width":80,"height":40}
            ]}}
        }}"""
        val snapshot = IrParser().parse(source).getOrThrow()
        compose.setContent {
            PyComposeTheme {
                Box(Modifier.testTag("outer")) {
                    Renderer(
                        BuiltinComponents.registry(),
                        ActionDispatcher {},
                    ).Render(snapshot)
                }
            }
        }
        compose.onNodeWithTag("outer").assertWidthIsEqualTo(87.dp).assertHeightIsEqualTo(51.dp)
    }

    private val brushConstructors =
        listOf(
            """{"type":"SolidColor","value":{"type":"Color","color":4294901760}}""",
            """{"type":"horizontalGradient","colors":[
                    {"type":"Color","color":4294901760},{"type":"Color","color":4278190335}]}""",
            """{"type":"verticalGradient","colors":[
                    {"type":"Color","color":4294901760},{"type":"Color","color":4278190335}]}""",
            """{"type":"linearGradient","colors":[
                    {"type":"Color","color":4294901760},{"type":"Color","color":4278190335}],
                    "start":{"type":"Offset","x":0,"y":0},"end":{"type":"Offset","x":40,"y":40}}""",
        )

    @Test fun everyEnabledBrushAndShapeHasNativeDrawingConsumption() {
        val brushes = mutableListOf<Brush>()
        val shapes = mutableListOf<Shape>()
        var drawingSize = Size.Zero
        compose.setContent {
            MaterialTheme {
                for (source in brushConstructors) {
                    brushes.add(
                        ValueResolver.brush(Json.parseToJsonElement(source)).getOrThrow(),
                    )
                }
                shapes.add(
                    ValueResolver
                        .shape(
                            Json.parseToJsonElement(
                                """{"type":"CutCornerShape","size":{"type":"Dp","value":8}}""",
                            ),
                        ).getOrThrow(),
                )
                shapes.add(
                    ValueResolver
                        .shape(
                            Json.parseToJsonElement("""{"type":"ThemeShape","name":"small"}"""),
                        ).getOrThrow(),
                )
                drawingSize =
                    ValueResolver
                        .size(
                            Json.parseToJsonElement("""{"type":"Size","width":40,"height":40}"""),
                        ).getOrThrow()
                androidx.compose.material3.Text(
                    "Draw",
                    style =
                        ValueResolver
                            .textStyle(
                                Json.parseToJsonElement(
                                    """{"type":"ThemeTypography","name":"titleLarge"}""",
                                ),
                            ).getOrThrow(),
                )
            }
        }
        compose.waitForIdle()
        for (brush in brushes) {
            for (shape in shapes) {
                assertDrawsClippedPixels(brush, shape, drawingSize)
            }
        }
    }

    private fun assertDrawsClippedPixels(
        brush: Brush,
        shape: Shape,
        drawingSize: Size,
    ) {
        val image = ImageBitmap(40, 40)
        val density = Density(1f)
        CanvasDrawScope().draw(density, LayoutDirection.Ltr, Canvas(image), drawingSize) {
            drawOutline(shape.createOutline(size, LayoutDirection.Ltr, density), brush)
        }
        val pixels = image.toPixelMap()
        assertTrue(pixels[20, 20].alpha > 0.99f)
        assertTrue(pixels[0, 0].alpha < 0.1f)
        assertTrue(pixels[3, 8].red > 0.5f)
        if (brush !is androidx.compose.ui.graphics.SolidColor) {
            assertTrue(pixels[36, 30].blue > 0.5f)
        }
    }
}
