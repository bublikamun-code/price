package com.priceweb.core.repository

import com.priceweb.core.ApiClient
import com.priceweb.core.CoreJson
import com.priceweb.core.CoreResult
import com.priceweb.core.MalformedResponseException
import com.priceweb.core.delete
import com.priceweb.core.get
import com.priceweb.core.guarded
import com.priceweb.core.post
import com.priceweb.core.model.LoginOutcome
import com.priceweb.core.model.NativeLoginRequest
import com.priceweb.core.model.SessionGrant
import com.priceweb.core.model.SessionSnapshot
import com.priceweb.core.model.SessionSummary
import com.priceweb.core.model.SuccessResponse
import com.priceweb.core.model.TwoFaChallenge
import com.priceweb.core.model.TwoFaVerifyRequest
import com.priceweb.core.postRaw
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.decodeFromJsonElement
import kotlinx.serialization.json.jsonObject

/**
 * Вход, refresh, профиль и журнал сессий (`/api/v2/auth`: sessions, 2fa, session).
 *
 * Репозиторий, а не UI, решает, чем является ответ входа: двумя токенами или
 * 2FA-челленджем. Экран входа получает уже разобранный [LoginOutcome] и не
 * занимается распознаванием «а токенов в ответе нет?».
 *
 * Ни один метод не бросает наружу: см. [CoreResult] — исключение, дошедшее до
 * Objective-C-экспорта, убивает процесс через `abort()`, поэтому наружу выходит
 * значение с ошибкой, а не исключение.
 */
class AuthRepository(private val api: ApiClient) {

    suspend fun login(email: String, password: String): CoreResult<LoginOutcome> =
        guarded("POST /api/v2/auth/sessions") {
            val raw = api.postRaw(
                path = "/api/v2/auth/sessions",
                body = NativeLoginRequest(
                    email = email.trim(),
                    password = password,
                    clientType = "NATIVE",
                    deviceName = api.device.deviceName,
                    osName = api.device.osName,
                    appVersion = api.device.appVersion,
                ),
                authenticated = false,
            )
            decodeLoginOutcome(raw.text)
        }

    /**
     * Разбор union-ответа входа: `SessionGrant` либо `TwoFaChallenge`.
     *
     * Различаем по наличию `accessToken` в `data` — это единственное поле,
     * которого нет в челлендже, и оно же означает, что сессия уже создана.
     */
    private suspend fun decodeLoginOutcome(text: String): LoginOutcome {
        val envelope = CoreJson.instance.decodeFromString<JsonObject>(text)
        val data = envelope["data"]?.jsonObject
            ?: throw MalformedResponseException("POST /api/v2/auth/sessions (нет поля data)")
        return if ("accessToken" in data) {
            val grant = CoreJson.instance.decodeFromJsonElement<SuccessResponse<SessionGrant>>(
                envelope,
            ).data
            api.adopt(grant)
            LoginOutcome.Granted(grant)
        } else {
            LoginOutcome.TwoFaRequired(
                CoreJson.instance.decodeFromJsonElement<SuccessResponse<TwoFaChallenge>>(
                    envelope,
                ).data,
            )
        }
    }

    suspend fun verifyTwoFa(ticket: String, code: String): CoreResult<SessionGrant> =
        guarded("POST /api/v2/auth/2fa/challenges/verify") {
            val response: SuccessResponse<SessionGrant> = api.post(
                path = "/api/v2/auth/2fa/challenges/verify",
                body = TwoFaVerifyRequest(
                    ticket = ticket,
                    code = code,
                    clientType = "NATIVE",
                    deviceName = api.device.deviceName,
                    osName = api.device.osName,
                    appVersion = api.device.appVersion,
                ),
                authenticated = false,
            )
            api.adopt(response.data)
            response.data
        }

    /** Текущий пользователь и коммерческий scope (`/api/v2/session`). */
    suspend fun currentSession(): CoreResult<SessionSnapshot> =
        guarded("GET /api/v2/session") {
            val response: SuccessResponse<SessionSnapshot> = api.get("/api/v2/session")
            response.data
        }

    /** Журнал сессий; [SessionSummary.current] отмечает ту, которой отвечает этот access-токен. */
    suspend fun sessions(): CoreResult<List<SessionSummary>> =
        guarded("GET /api/v2/auth/sessions") {
            val response: SuccessResponse<List<SessionSummary>> = api.get("/api/v2/auth/sessions")
            response.data
        }

    /**
     * Выход с текущего устройства.
     *
     * Локальные токены стираются даже если сеть отвалилась (иначе приложение
     * останется «залогиненным» в офлайне с мёртвым токеном), поэтому
     * [ApiClient.forget] живёт в `finally`, а ошибка сети — обычный [CoreError].
     */
    suspend fun logout(): CoreResult<Unit> = guarded("DELETE /api/v2/auth/sessions/current") {
        try {
            api.delete("/api/v2/auth/sessions/current")
        } finally {
            api.forget()
        }
    }

    /** Отзыв конкретной сессии из журнала. */
    suspend fun revokeSession(sessionId: String): CoreResult<Unit> =
        guarded("DELETE /api/v2/auth/sessions/$sessionId") {
            api.delete("/api/v2/auth/sessions/$sessionId")
        }

    /** Тихо забывает локальные токены — например, после 401 по refresh. */
    suspend fun forgetLocalSession(): CoreResult<Unit> = guarded("local forget") { api.forget() }
}
