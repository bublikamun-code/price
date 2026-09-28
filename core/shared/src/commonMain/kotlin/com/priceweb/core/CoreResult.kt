package com.priceweb.core

import io.ktor.client.plugins.HttpRequestTimeoutException
import io.ktor.utils.io.errors.IOException
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.serialization.SerializationException

/**
 * Ошибка, разобранная до того, как пересечь границу Objective-C.
 *
 * Отдельный тип вместо «просто покажи `message` исключения» по одной причине:
 * нативный UI должен различать *виды* отказа. «Нет связи» просят повторить
 * позже, `INVALID_CREDENTIALS` возвращают на экран входа, а 401 означает, что
 * сессию надо забыть, — и всё это видно по [code] без разбора текста.
 */
data class CoreError(
    val code: String,
    val status: Int,
    val message: String,
    /** Настоящая причина, для журнала: пользователю она не показывается. */
    val debug: String? = null,
) {
    val isAuthFailure: Boolean
        get() = status == 401 || code == "AUTHENTICATION_REQUIRED" || code == "TOKEN_EXPIRED"

    val isCredentialsFailure: Boolean
        get() = code == "INVALID_CREDENTIALS" || code == "TWO_FA_CODE_INVALID"

    val isNetworkFailure: Boolean
        get() = code == NETWORK_UNAVAILABLE

    companion object {
        /** Сервер недоступен: нет сети, DNS не отвечает, соединение оборвалось. */
        const val NETWORK_UNAVAILABLE = "NETWORK_UNAVAILABLE"

        /** Ответ есть, но он не соответствует контракту. */
        const val MALFORMED_RESPONSE = "MALFORMED_RESPONSE"

        /** Не-2xx без problem+json: ответил прокси или что-то не то. */
        const val UNEXPECTED_RESPONSE = "UNEXPECTED_RESPONSE"

        /** Всё остальное. Сюда попадают баги ядра — их надо чинить, а не показывать. */
        const val UNEXPECTED_ERROR = "UNEXPECTED_ERROR"
    }
}

/**
 * Результат вызова ядра: либо значение, либо готовая к показу ошибка.
 *
 * Существует из-за правила Objective-C-экспорта `suspend`-функций: Kotlin
 * отдаёт их как метод с `completionHandler`, у которого параметр ошибки —
 * это `NSError*`, **а не** error-параметр в смысле Swift. Objective-C-рантайм
 * не может превратить произвольное Kotlin-исключение в `NSError`, если класс
 * исключения не объявлен в `@Throws` у метода, — и не объявляет его никогда.
 * Исключение, дошедшее до границы, попадает в
 * `Kotlin_ObjCExport_runCompletionFailure` → `terminateWithUnhandledException`
 * → `abort()`. То есть **любая** ошибка сети убивала приложение целиком,
 * вместо того чтобы показать «нет связи».
 *
 * Поэтому наружу выходит значение, а не исключение: [guarded] ловит всё
 * внутри Kotlin и превращает в [CoreError].
 */
data class CoreResult<T>(
    val value: T?,
    val error: CoreError?,
) {
    val isSuccess: Boolean get() = error == null

    companion object {
        fun <T> ok(value: T): CoreResult<T> = CoreResult(value = value, error = null)

        fun <T> fail(error: CoreError): CoreResult<T> = CoreResult(value = null, error = error)
    }
}

/**
 * Тело ответа не соответствует контракту.
 *
 * Отдельный класс вместо `IllegalStateException` по той же причине, что и
 * [CoreResult]: тип ошибки должен быть виден UI, а не теряться в тексте.
 */
class MalformedResponseException(what: String) :
    Exception("Ответ $what не соответствует контракту")

/**
 * Обёртка для всего, что видно нативному UI: ни одна `suspend`-функция ядра
 * не должна бросать через границу Objective-C.
 *
 * [CancellationException] обрабатывается отдельно и не всегда означает отмену:
 * движок Ktor на iOS закрывает канал запроса именно им, когда до сервера
 * не дошло дело (нет сети, хост не отвечает). Отличить «сеть упала» от
 * «экран ушёл с задачей» можно единственным способом — спросить у текущей
 * корутины, жива ли она: `ensureActive()` бросит заново, только если отменён
 * именно наш job.
 */
suspend inline fun <T> guarded(what: String, block: () -> T): CoreResult<T> = try {
    CoreResult.ok(block())
} catch (cancellation: CancellationException) {
    currentCoroutineContext().ensureActive()
    CoreResult.fail(
        CoreError(
            code = CoreError.NETWORK_UNAVAILABLE,
            status = 0,
            message = "Нет связи с сервером. Проверьте подключение и попробуйте ещё раз.",
        ),
    )
} catch (failure: Throwable) {
    CoreResult.fail(failure.asCoreError(what))
}

/** Тот же [guarded], но результат не нужен: успех и ошибка уже записаны в состояние. */
suspend inline fun guardQuietly(block: () -> Unit) {
    guarded("", block)
}

/** Перевод любого отказа в плоский [CoreError], понятный пользователю. */
fun Throwable.asCoreError(what: String): CoreError = when (this) {
    is ApiException -> CoreError(code = code, status = status, message = message)
    is UnexpectedResponseException -> CoreError(
        code = CoreError.UNEXPECTED_RESPONSE,
        status = status,
        message = "Сервер ответил неожиданно (HTTP $status).",
        debug = bodyPreview,
    )
    is MalformedResponseException, is SerializationException -> CoreError(
        code = CoreError.MALFORMED_RESPONSE,
        status = 0,
        message = message ?: "Ответ $what не соответствует контракту",
        debug = toString(),
    )
    is HttpRequestTimeoutException -> CoreError(
        code = CoreError.NETWORK_UNAVAILABLE,
        status = 0,
        message = "Сервер не ответил вовремя. Попробуйте ещё раз.",
        debug = toString(),
    )
    is IOException -> CoreError(
        code = CoreError.NETWORK_UNAVAILABLE,
        status = 0,
        message = "Нет связи с сервером. Проверьте подключение и попробуйте ещё раз.",
        debug = toString(),
    )
    else -> CoreError(
        code = CoreError.UNEXPECTED_ERROR,
        status = 0,
        message = message ?: "Что-то пошло не так ($what).",
        debug = toString(),
    )
}
