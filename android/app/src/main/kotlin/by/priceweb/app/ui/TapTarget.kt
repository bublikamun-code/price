package by.priceweb.app.ui

import androidx.compose.foundation.clickable
import androidx.compose.ui.Modifier

/**
 * Отклик без заливки.
 *
 * У ссылок внутри потока настроек стандартная волна нажатия читается как ошибка
 * ввода, а не как подтверждение действия, поэтому здесь она убрана, а сам
 * клик остаётся.
 */
fun Modifier.tapTarget(onClick: () -> Unit): Modifier = clickable(
    interactionSource = null,
    indication = null,
    onClick = onClick,
)
