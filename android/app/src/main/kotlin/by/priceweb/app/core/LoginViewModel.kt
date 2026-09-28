package by.priceweb.app.core

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.priceweb.core.CoreError
import com.priceweb.core.model.LoginOutcome
import com.priceweb.core.repository.AuthRepository
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * Экран входа: почта, пароль и — при включённой 2FA — проверка кода.
 *
 * Ответ сервера разбирает репозиторий, а не экран: здесь мы получаем уже
 * готовый `LoginOutcome` и не разбираемся, токены в ответе или челлендж.
 *
 * Репозиторий ничего не бросает — он возвращает `CoreResult`. Это не
 * перестраховка ради красоты: тот же слой ядра работает на iOS, где
 * Objective-C-экспорт превращает бросок из `suspend`-функции в `abort()`,
 * и потому граница обязана быть небросающей на обеих платформах.
 */
class LoginViewModel(private val auth: AuthRepository) : ViewModel() {

    data class UiState(
        val email: String = "",
        val password: String = "",
        val code: String = "",
        val ticket: String? = null,
        val isSubmitting: Boolean = false,
        val error: String? = null,
    ) {
        val awaitingCode: Boolean get() = ticket != null
        val canSubmit: Boolean
            get() = !isSubmitting && if (awaitingCode) {
                code.length >= 6
            } else {
                email.contains('@') && password.length >= 8
            }
    }

    private val _state = MutableStateFlow(UiState())
    val state: StateFlow<UiState> = _state.asStateFlow()

    /** Событие «сессия получена» — экран слушает его одноразово. */
    private val _authenticated = MutableStateFlow(false)
    val authenticated: StateFlow<Boolean> = _authenticated.asStateFlow()

    fun onEmail(value: String) = _state.update { it.copy(email = value, error = null) }

    fun onPassword(value: String) = _state.update { it.copy(password = value, error = null) }

    fun onCode(value: String) = _state.update {
        it.copy(code = value.filter(Char::isDigit).take(6), error = null)
    }

    fun backToCredentials() = _state.update {
        it.copy(ticket = null, code = "", error = null)
    }

    fun submit() {
        val current = _state.value
        if (!current.canSubmit) return
        _state.update { it.copy(isSubmitting = true, error = null) }

        viewModelScope.launch {
            if (current.ticket != null) {
                val result = auth.verifyTwoFa(current.ticket, current.code)
                if (result.isSuccess) {
                    _authenticated.value = true
                } else {
                    // Неверный код не должен стирать поле ввода: пользователь
                    // имеет право исправить его, не начиная вход заново.
                    _state.update { it.copy(error = result.error.userMessage(), code = "") }
                }
            } else {
                val result = auth.login(current.email, current.password)
                val outcome = result.value
                when {
                    outcome == null ->
                        _state.update { it.copy(error = result.error.userMessage()) }
                    outcome is LoginOutcome.Granted ->
                        _authenticated.value = true
                    outcome is LoginOutcome.TwoFaRequired ->
                        _state.update { it.copy(ticket = outcome.challenge.ticket, code = "") }
                }
            }
            _state.update { it.copy(isSubmitting = false) }
        }
    }
}

/**
 * Текст ошибки для пользователя.
 *
 * Ядро кладёт в `CoreError.message` и `detail` из problem+json — то есть тот
 * текст, который писал бэкенд для пользователя, — поэтому переписывать его
 * на клиенте не нужно: вторая копия сообщений разъедется с серверной при
 * первой же правке. Для случая без `CoreError` (сбой в самом экране) текст
 * остаётся общим.
 */
fun CoreError?.userMessage(): String =
    this?.message?.takeIf { it.isNotBlank() }
        ?: "Что-то пошло не так. Попробуйте ещё раз."
