package com.pycompose.host.ui

import android.annotation.SuppressLint
import android.util.Log
import androidx.compose.foundation.Image
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.produceState
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.painter.Painter
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import com.pycompose.host.BuildConfig
import com.pycompose.host.resources.ResourceResolver
import com.pycompose.ir.ResourceReference
import com.pycompose.ir.generated.TextProps
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

// Result state is assigned after IO and observed by the Compose integration test.
@Composable
@SuppressLint("ProduceStateDoesNotAssignValue")
fun ResourceImage(
    reference: String,
    description: String?,
    modifier: Modifier,
    resources: ResourceResolver?,
) {
    val result by produceState<Result<Painter>?>(null, reference, resources) {
        value = null
        value = loadImage(resources, reference)
    }
    ResourceDiagnostic(result?.exceptionOrNull())
    result?.getOrNull()?.let { Image(it, description, modifier) }
    if (BuildConfig.DEBUG && result?.isFailure == true) {
        Text("Missing resource: $reference", modifier)
    }
}

private suspend fun loadImage(
    resources: ResourceResolver?,
    reference: String,
): Result<Painter> =
    withContext(Dispatchers.IO) {
        resources?.image(reference) ?: Result.failure(
            IllegalStateException("No resource provider"),
        )
    }

@Composable
@SuppressLint("ProduceStateDoesNotAssignValue")
fun ResourceText(
    props: TextProps,
    modifier: Modifier,
    color: Color,
    style: TextStyle,
    resources: ResourceResolver?,
) {
    val reference = props.resource
    val locale = props.locale
    val font = props.fontResource
    val text by produceState<Result<String>?>(null, reference, locale, resources) {
        value = null
        if (reference != null && resources != null) {
            value =
                withContext(Dispatchers.IO) {
                    ResourceReference.parse(reference, setOf("string", "asset")).mapCatching {
                        if (it.kind == "string") {
                            resources.string(it.name, locale).getOrThrow()
                        } else {
                            resources
                                .asset(it.name)
                                .getOrThrow()
                                .decodeToString(throwOnInvalidSequence = true)
                        }
                    }
                }
        }
    }
    val family by produceState<Result<FontFamily>?>(null, font, resources) {
        value = null
        if (font != null && resources != null) {
            value =
                withContext(Dispatchers.IO) {
                    ResourceReference.parse(font, setOf("font")).mapCatching {
                        resources.font(it.name).getOrThrow()
                    }
                }
        }
    }
    ResourceDiagnostic(text?.exceptionOrNull())
    ResourceDiagnostic(family?.exceptionOrNull())
    Text(
        text?.getOrDefault(props.text) ?: props.text,
        modifier,
        color = color,
        style = style,
        fontFamily = family?.getOrNull(),
    )
}

@Composable private fun ResourceDiagnostic(failure: Throwable?) {
    LaunchedEffect(failure) {
        if (failure != null) Log.w("PyCompose", "Resource unavailable: ${failure.message}")
    }
}
