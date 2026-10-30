package com.pycompose.renderer

import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/** All fallible conversions are values; malformed props never throw into Compose. */
object PropResolver {
    fun dp(value: Double): Result<Dp> =
        runCatching {
            require(value.isFinite() && value >= 0 && value <= Float.MAX_VALUE.toDouble()) {
                "Invalid dp: $value"
            }
            value.toFloat().dp
        }
}
