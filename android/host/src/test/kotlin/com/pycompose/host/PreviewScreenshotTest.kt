package com.pycompose.host

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onRoot
import com.pycompose.host.ui.BuiltinComponents
import com.pycompose.host.ui.PyComposeTheme
import com.pycompose.ir.IrParser
import com.pycompose.renderer.ActionDispatcher
import com.pycompose.renderer.Renderer
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.ParameterizedRobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import java.io.File
import kotlin.math.abs

/**
 * The screenshot comparison (plan 31 §10): each catalog sample against its reference.
 *
 * Informational, as plan 31 §13 decision 4 settles: a fidelity change is seen,
 * not failed, because references recorded on one platform's fonts do not match
 * another's pixel for pixel. A difference writes the new image and a line to
 * `build/reports/screenshots/summary.txt`. A missing reference is recorded;
 * `-Ppycompose.recordScreenshots=true` re-records them all. A component that
 * opens its own window captures as its host screen; plan 31 §10 renders those
 * on an emulator.
 */
@RunWith(ParameterizedRobolectricTestRunner::class)
@Config(sdk = [34], application = android.app.Application::class, qualifiers = "w360dp-h640dp-mdpi")
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class PreviewScreenshotTest(
    private val component: String,
) {
    @get:Rule val compose = createComposeRule()

    @Test
    fun theSampleIsComparedWithItsReference() {
        val source = checkNotNull(javaClass.getResource("/previews/$component.json")).readText()
        val ir = IrParser().parse(source).getOrThrow()
        val renderer = Renderer(BuiltinComponents.registry(), ActionDispatcher {})
        // A fixed full-window frame: a component with no size of its own
        // (Spacer) or one that opens its own window (a sheet) still captures.
        compose.setContent {
            PyComposeTheme {
                Box(Modifier.fillMaxSize().background(Color.White)) { renderer.Render(ir) }
            }
        }
        compose.waitForIdle()
        compare(component, compose.onRoot().captureToImage().asAndroidBitmap())
    }

    companion object {
        private val references = File("src/test/screenshots")
        private val reports = File("build/reports/screenshots")
        private const val CHANNEL_TOLERANCE = 8
        private const val PIXEL_TOLERANCE = 0.005

        @JvmStatic
        @ParameterizedRobolectricTestRunner.Parameters(name = "{0}")
        fun components(): List<Array<Any>> =
            checkNotNull(PreviewScreenshotTest::class.java.getResource("/previews/index.txt"))
                .readText()
                .lines()
                .filter { it.isNotBlank() }
                .map { arrayOf(it) }

        private fun compare(
            name: String,
            actual: Bitmap,
        ) {
            val reference = File(references, "$name.png")
            if (System.getProperty("pycompose.recordScreenshots") == "true" || !reference.isFile) {
                write(reference, actual)
                return
            }
            val expected = BitmapFactory.decodeFile(reference.path)
            val differing = differing(expected, actual)
            if (differing > PIXEL_TOLERANCE) {
                write(File(reports, "$name.png"), actual)
                reports.mkdirs()
                File(reports, "summary.txt").appendText(
                    "$name: %.2f%% of pixels differ from %s\n".format(differing * 100, reference),
                )
            }
        }

        /** The share of pixels whose channels move past the tolerance; 1 if sizes differ. */
        private fun differing(
            expected: Bitmap,
            actual: Bitmap,
        ): Double {
            if (expected.width != actual.width || expected.height != actual.height) return 1.0
            val count = expected.width * expected.height
            val left =
                IntArray(count).also {
                    expected.getPixels(it, 0, expected.width, 0, 0, expected.width, expected.height)
                }
            val right =
                IntArray(count).also {
                    actual.getPixels(it, 0, actual.width, 0, 0, actual.width, actual.height)
                }
            val moved =
                left.indices.count { index ->
                    (0 until 32 step 8).any { shift ->
                        abs((left[index] shr shift and 0xFF) - (right[index] shr shift and 0xFF)) >
                            CHANNEL_TOLERANCE
                    }
                }
            return moved.toDouble() / count
        }

        private fun write(
            file: File,
            image: Bitmap,
        ) {
            file.parentFile?.mkdirs()
            file.outputStream().use { image.compress(Bitmap.CompressFormat.PNG, 100, it) }
        }
    }
}
