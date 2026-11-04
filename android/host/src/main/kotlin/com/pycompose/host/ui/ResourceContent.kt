package com.pycompose.host.ui

import android.annotation.SuppressLint
import android.util.Log
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.produceState
import androidx.compose.ui.graphics.painter.Painter
import androidx.compose.ui.text.font.FontFamily
import com.pycompose.host.BuildConfig
import com.pycompose.host.resources.ResourceResolver
import com.pycompose.ir.ResourceReference
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/*
 * A resource prop names a native parameter it fills: the generated adapter reads it here, off
 * the Compose thread, and passes what arrives in that parameter's place. Each reader is null
 * until its value arrives, and stays null when it cannot, with the failure logged; the adapter
 * then falls back to the plain prop, or composes nothing when there is none.
 */

/**
 * The string or asset text [reference] names, in [locale].
 *
 * @param reference A `string:` or `asset:` reference, or null when the prop is absent.
 * @param locale The locale to read a string in; null reads the device's.
 * @return The text, or null until it arrives or when it cannot.
 */
@Composable
fun ResourceResolver?.resourceText(
    reference: String?,
    locale: String?,
): String? =
    loaded(reference, locale) { resources, name ->
        ResourceReference.parse(name, setOf("string", "asset")).mapCatching {
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

/**
 * The font family [reference] names.
 *
 * @param reference A `font:` reference, or null when the prop is absent.
 * @return The family, or null until it arrives or when it cannot.
 */
@Composable
fun ResourceResolver?.resourceFont(reference: String?): FontFamily? =
    loaded(reference) { resources, name ->
        ResourceReference.parse(name, setOf("font")).mapCatching {
            resources.font(it.name).getOrThrow()
        }
    }

/**
 * The image [reference] names; a debug build shows which one is missing in its place.
 *
 * @param reference A `drawable:`, `asset:` or `file:` reference.
 * @return The painter, or null until it arrives or when it cannot.
 */
@Composable
fun ResourceResolver?.resourceImage(reference: String?): Painter? {
    var failed = false
    val painter =
        loaded(
            reference,
            onFailure = { failed = true },
        ) { resources, name -> resources.image(name) }
    if (BuildConfig.DEBUG && failed) Text("Missing resource: $reference")
    return painter
}

// Result state is assigned after IO and observed by the Compose integration test.
@Composable
@SuppressLint("ProduceStateDoesNotAssignValue")
private fun <T : Any> ResourceResolver?.loaded(
    reference: String?,
    vararg keys: Any?,
    onFailure: () -> Unit = {},
    load: (ResourceResolver, String) -> Result<T>,
): T? {
    val result by produceState<Result<T>?>(null, reference, this, *keys) {
        value = null
        val resources = this@loaded
        if (reference != null) {
            value =
                if (resources == null) {
                    Result.failure(IllegalStateException("No resource provider"))
                } else {
                    withContext(Dispatchers.IO) { load(resources, reference) }
                }
        }
    }
    val failure = result?.exceptionOrNull()
    LaunchedEffect(failure) {
        if (failure != null) Log.w("PyCompose", "Resource unavailable: ${failure.message}")
    }
    if (failure != null) onFailure()
    return result?.getOrNull()
}
