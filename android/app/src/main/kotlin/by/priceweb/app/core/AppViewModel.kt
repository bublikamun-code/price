package by.priceweb.app.core

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.priceweb.core.model.CurrentUser
import com.priceweb.core.repository.AuthRepository
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/** Состояние приложения верхнего уровня: залогинен или нет. */
sealed interface SessionState {
    data object Restoring : SessionState
    data object Anonymous : SessionState
    data class Authenticated(val user: CurrentUser) : SessionState
}

/**
 * Гейт авторизации.
 *
 * Токен лежит в EncryptedSharedPreferences, поэтому после перезапуска
 * приложение может остаться «залогиненным» без повторного входа. Но refresh
 * могло истекнуть, поэтому граница доверия одна — сервер: спрашиваем
 * `/api/v2/session`. Отказ здесь не ошибка приложения, а обычное «войдите
 * заново».
 */
class AppViewModel(private val auth: AuthRepository) : ViewModel() {

    private val _session = MutableStateFlow<SessionState>(SessionState.Restoring)
    val session: StateFlow<SessionState> = _session.asStateFlow()

    fun restore() {
        viewModelScope.launch { refresh() }
    }

    fun refresh() {
        viewModelScope.launch {
            // Репозиторий возвращает CoreResult, а не бросает: отказ здесь —
            // это обычное «войдите заново», а не ошибка приложения.
            val user = auth.currentSession().value?.user
            _session.value = if (user != null) {
                SessionState.Authenticated(user)
            } else {
                SessionState.Anonymous
            }
        }
    }

    fun didAuthenticate() {
        refresh()
    }

    /**
     * Выход. Локальные токены стираются в любом случае — внутри репозитория
     * они удаляются в `finally`, — поэтому недоступный сервер не должен
     * оставлять пользователя в приложении с мёртвой сессией.
     */
    fun signOut() {
        viewModelScope.launch {
            auth.logout()
            _session.value = SessionState.Anonymous
        }
    }
}
