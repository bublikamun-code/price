package by.priceweb.app.ui

import android.os.Build
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext

/**
 * Оформление приложения.
 *
 * Палитра та же, что на web и в iOS: графит и один акцент. Точные цвета
 * брендинга — не тема материала, а значения ниже, поэтому динамический цвет
 * Android включается только на Android 12+ и не меняет вид на старых версиях.
 */
private val LightColors = lightColorScheme(
    primary = Color(0xFF2E5A88),
    onPrimary = Color.White,
    secondary = Color(0xFF4A5A6A),
    surfaceVariant = Color(0xFFEDF0F3),
)

private val DarkColors = darkColorScheme(
    primary = Color(0xFF9EC4EA),
    onPrimary = Color(0xFF0F2537),
    secondary = Color(0xFFB6C4D2),
    surfaceVariant = Color(0xFF2A3138),
)

@Composable
fun PriceWebTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit,
) {
    val context = LocalContext.current
    val colors = when {
        Build.VERSION.SDK_INT >= Build.VERSION_CODES.S ->
            if (darkTheme) dynamicDarkColorScheme(context) else dynamicLightColorScheme(context)
        darkTheme -> DarkColors
        else -> LightColors
    }
    MaterialTheme(colorScheme = colors, content = content)
}
