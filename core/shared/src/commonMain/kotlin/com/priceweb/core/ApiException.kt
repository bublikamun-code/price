package com.priceweb.core

import com.priceweb.core.model.ProblemDetails
import kotlinx.serialization.SerializationException

/**
 * Ошибка API v2, разобранная из RFC 9457 problem+json.
 *
 * У клиента две разные потребности: показать пользователю [detail] и отреагировать
 * программно на [code] («показать форму 2FA», «сбросить курсор и перезапросить»).
 * Поэтому [code] — главное, а текст остаётся запасным вариантом для UI.
 */
class ApiException(
    val code: String,
    val status: Int,
    override val message: String,
    val problem: ProblemDetails? = null,
) : Exception(message) {

    /** Токен недействителен или истёк — клиенту пора обновить сессию. */
    val isAuthenticationFailure: Boolean
        get() = status == 401 || code == "AUTHENTICATION_REQUIRED" || code == "TOKEN_EXPIRED"

    /** Пароль/2FA отвергнуты: это не повод стирать токены, только показать ошибку. */
    val isCredentialsFailure: Boolean
        get() = code == "INVALID_CREDENTIALS" || code == "TWO_FA_CODE_INVALID"

    /** Превышен лимит попыток входа или проверки кода. */
    val isRateLimited: Boolean
        get() = status == 429 || code == "RATE_LIMITED"

    val requestId: String?
        get() = problem?.requestId
}

/** Ответ не problem+json и не распознан — сервер или прокси ответил не тем. */
class UnexpectedResponseException(
    val status: Int,
    val bodyPreview: String,
) : Exception("Неожиданный ответ API: HTTP $status")

internal fun throwApiException(problem: ProblemDetails?, status: Int, body: String): Nothing {
    if (problem == null) throw UnexpectedResponseException(status, body.take(500))
    throw ApiException(
        code = problem.code ?: "HTTP_$status",
        status = problem.status ?: status,
        message = problem.detail ?: problem.title ?: "Ошибка запроса",
        problem = problem,
    )
}

internal fun <T> decodeOrThrow(
    decode: (String) -> T,
    body: String,
    what: String,
): T = try {
    decode(body)
} catch (exc: SerializationException) {
    // Именно этот тип, а не IllegalStateException: [asCoreError] отличает по нему
    // «сервер ответил не тем» от настоящего бага ядра, и текст уходит в UI.
    throw MalformedResponseException("$what (${exc.message})")
}
