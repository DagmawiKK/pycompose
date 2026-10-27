package com.pycompose.host.ui

import android.os.Build
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.platform.LocalContext

/** The app's [AppTheme], generated from `[theme]` in `pycompose.toml`. */
@Composable
fun PyComposeTheme(content: @Composable () -> Unit) {
    val dark = AppTheme.darkMode ?: isSystemInDarkTheme()
    val context = LocalContext.current
    val colors =
        when {
            AppTheme.DYNAMIC && Build.VERSION.SDK_INT >= Build.VERSION_CODES.S ->
                if (dark) dynamicDarkColorScheme(context) else dynamicLightColorScheme(context)
            dark -> AppTheme.darkColors ?: darkColorScheme()
            else -> AppTheme.lightColors ?: lightColorScheme()
        }
    MaterialTheme(
        colorScheme = colors,
        typography = AppTheme.typography,
        shapes = AppTheme.shapes,
        content = content,
    )
}
