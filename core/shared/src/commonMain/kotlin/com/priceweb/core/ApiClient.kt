package com.priceweb.core

import com.priceweb.core.model.ProblemDetails
import com.priceweb.core.model.SessionGrant
import com.priceweb.core.model.SessionRefreshRequest
import com.priceweb.core.model.SuccessResponse
import com.priceweb.core.session.AccessToken
import com.priceweb.core.session.TokenStore
import io.ktor.client.HttpClient
import io.ktor.client.request.HttpRequestBuilder
import io.ktor.client.request.header
import io.ktor.client.request.request
import io.ktor.client.request.setBody
import io.ktor.client.statement.bodyAsText
import io.ktor.http.ContentType
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpMethod
import io.ktor.http.HttpStatusCode
import io.ktor.http.contentType
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.datetime.Clock
import kotlinx.datetime.Instant
import kotlinx.serialization.json.Json
import kotlin.concurrent.Volatile
import kotlin.time.Duration.Companion.seconds

/** Метаданные устройства, которые сервер кладёт в журнал сессий (§16 п.36). */
data class DeviceInfo(
    val deviceName: String,
    val osName: String,
    val appVersion: String,
)

/** Статус + тело, прочитанные ровно один раз: тело Ktor не перечитывается. */
/**
 * «Голый» ответ без декодирования.
 *
 * [sentAccess] — access-токен, с которым запрос ушёл в сеть (null для анонимного).
 * Он нужен 401-ветке: по нему видно, что конкретно сервер отверг, и можно отличить
 * «мой токен протух» от «пока я ждал, refresh уже кто-то выполнил».
 */
internal data class RawResponse(
    val status: Int,
    val text: String,
    val sentAccess: String? = null,
)

/**
 * Тонкая обёртка над `/api/v2` для нативных клиентов.
 *
 * Держит три инварианта, которые иначе пришлось бы повторять в каждом экране:
 * access-токен живёт в памяти, refresh случается не чаще раза за раз даже при
 * десяти одновременных 401, и каждый запрос переживает ровно один ретрай.
 *
 * Движок HTTP (CIO / Darwin / OkHttp) задаётся снаружи: общему коду не положено
 * знать про платформенные движки.
 */
class ApiClient(
    private val baseUrl: String,
    private val http: HttpClient,
    private val tokenStore: TokenStore,
    val device: DeviceInfo,
    private val json: Json = CoreJson.instance,
) {
    private val refreshMutex = Mutex()
    private var inFlightRefresh: CompletableDeferred<AccessToken>? = null

    @Volatile
    private var tokens: AccessToken? = null

    private var loaded = false

    @Volatile
    private var accessExpiresAt: Instant? = null

    /** Токен, попадающий в `Authorization`, без обращения к хранилищу. */
    val accessToken: String?
        get() = tokens?.value

    /**
     * Токены из памяти, без обращения к сети.
     *
     * null, если хранилище пустое **или** его не удалось прочитать: Keychain
     * на этой границе тоже бросает (см. [CoreResult]), и поднимать это в UI
     * незачем — следующий вызов разберётся сам.
     */
    suspend fun currentTokens(): AccessToken? = try {
        ensureLoaded()
        tokens
    } catch (_: Throwable) {
        null
    }

    /**
     * Access-токен, пригодный для чужого HTTP-клиента.
     *
     * Нужен нативным слоям: SwiftUI грузит картинки через URLSession, а не
     * через Ktor, и `Authorization` там надо проставить самому. Отдавать просто
     * [accessToken] нельзя — он может быть на грани срока, и запрос уйдёт с
     * заведомо мёртвым токеном. Здесь та же логика запасного интервала, что и в
     * [tokenForRequest], поэтому поведение совпадает с API-вызовами.
     *
     * Пустая строка вместо `null` — не украшение: Objective-C-экспорт помечает
     * nullable-результат как «non-null, но бывает nil», и на стороне Swift это
     * превращается в неоднозначный мост. Пустой токен в `Authorization` не
     * положить, так что проверять его всё равно нужно.
     *
     * Отказ сети здесь — тоже пустая строка, а не исключение: вызывающий
     * (загрузчик фото) ничего не сможет с ним сделать, кроме как не показать
     * закрытую картинку, а бросок через границу Objective-C убил бы процесс
     * (см. [CoreResult]).
     */
    suspend fun validAccessToken(): String = try {
        tokenForRequest()?.value.orEmpty()
    } catch (_: Throwable) {
        ""
    }

    /**
     * Кладёт grant в память и в защищённое хранилище.
     * Вызывается репозиторием сразу после успешного входа или refresh.
     */
    suspend fun adopt(grant: SessionGrant) {
        tokens = AccessToken(grant.accessToken, grant.refreshToken)
        accessExpiresAt = grant.accessTokenExpiresAt
        loaded = true
        tokenStore.save(grant)
    }

    /** Локальный выход: стирает токены, не обращаясь к серверу. */
    suspend fun forget() {
        tokens = null
        accessExpiresAt = null
        loaded = true
        tokenStore.clear()
    }

    private suspend fun ensureLoaded() {
        if (loaded) return
        // Повторная загрузка идемпотентна, а гонку двух первых обращений
        // безвредно разрешает чтение одного и того же grant.
        loaded = true
        val stored = tokenStore.load()
        if (stored != null) {
            tokens = AccessToken(stored.accessToken, stored.refreshToken)
            accessExpiresAt = stored.accessTokenExpiresAt
        }
    }

    internal suspend fun sendRaw(
        method: HttpMethod,
        path: String,
        authenticated: Boolean,
        body: Any?,
        block: HttpRequestBuilder.() -> Unit,
    ): RawResponse {
        ensureLoaded()
        val url = baseUrl.trimEnd('/') + path

        if (authenticated) {
            val token = tokenForRequest()
            if (token != null) {
                return http.request(url) {
                    this.method = method
                    header(HttpHeaders.Authorization, "Bearer ${token.value}")
                    applyBody(body)
                    block()
                }.readOnce(sentAccess = token.value)
            }
            // Токена нет: запрос уйдёт анонимно. Если refresh-токен ещё где-то
            // есть, ветка 401 в execute() его подхватит.
        }
        return http.request(url) {
            this.method = method
            applyBody(body)
            block()
        }.readOnce()
    }

    /** Refresh идёт мимо [sendRaw]: иначе его собственный 401-ретрай увёл бы в рекурсию. */
    private suspend fun refreshOnce(refreshToken: String): RawResponse =
        http.request(baseUrl.trimEnd('/') + "/api/v2/auth/sessions/refresh") {
            method = HttpMethod.Post
            contentType(ContentType.Application.Json)
            setBody(SessionRefreshRequest(refreshToken))
        }.readOnce()

    private suspend fun io.ktor.client.statement.HttpResponse.readOnce(
        sentAccess: String? = null,
    ): RawResponse =
        RawResponse(status.value, runCatching { bodyAsText() }.getOrDefault(""), sentAccess)

    private fun HttpRequestBuilder.applyBody(body: Any?) {
        if (body == null) return
        contentType(ContentType.Application.Json)
        setBody(body)
    }

    /**
     * Токен для исходящего запроса, при необходимости обновлённый.
     *
     * Access живёт 15 минут, поэтому запас в минуту: без него запрос, начатый
     * перед границей, гарантированно получил бы 401 и лишний round-trip.
     */
    private suspend fun tokenForRequest(): AccessToken? {
        val current = tokens ?: return null
        val expiry = accessExpiresAt
        if (expiry == null || Clock.System.now() < expiry.minus(60.seconds)) return current
        return runCatching { refreshSingleFlight() }.getOrNull()
    }

    /**
     * Обновление токенов «в одном полёте».
     *
     * Если десять экранов одновременно упёрлись в 401, refresh должен уйти один
     * раз: иначе бэкенд увидит цепочку ротаций, часть из которых — повторное
     * использование уже отозванного refresh-токена, и завершит всю сессию как
     * подозрительную.
     *
     * [staleAccess] — токен, с которым вызывающий отправил запрос и получил 401.
     * Он же отличает два разных случая: «этот токен ещё актуален, обновляйся» и
     * «пока я летел, refresh уже случился, просто возьми новый токен». Второй
     * случай обязан обойтись без сети — иначе гонка, при которой последний из
     * пяти 401-ответов приходит уже после завершения лидера, становится новым
     * лидером и устраивает вторую ротацию, бэкенд же расценивает повторное
     * использование отозванного refresh-токена как кражу сессии.
     */
    internal suspend fun refreshSingleFlight(staleAccess: String? = null): AccessToken {
        val mine = CompletableDeferred<AccessToken>()
        var alreadyRefreshed = false
        val leader = refreshMutex.withLock {
            val existing = inFlightRefresh
            val current = tokens
            when {
                existing != null -> existing
                staleAccess != null && current != null && current.value != staleAccess -> {
                    alreadyRefreshed = true
                    null
                }
                else -> {
                    inFlightRefresh = mine
                    mine
                }
            }
        }
        if (alreadyRefreshed) return tokens!!
        if (leader != mine) return leader?.await() ?: tokens!!

        try {
            val refreshToken = tokens?.refreshToken
                ?: throw ApiException(
                    code = "AUTHENTICATION_REQUIRED",
                    status = 401,
                    message = "Сессия не найдена",
                )
            val raw = refreshOnce(refreshToken)
            if (raw.status >= 400) throwApiException(parseProblem(raw.text), raw.status, raw.text)
            // Refresh отдаёт ту же обёртку SuccessResponse, что и login: grant
            // лежит в `data`, а не в корне. Декодировать корень — значит упасть
            // на каждом обновлении токена.
            val grant = decodeOrThrow(
                { json.decodeFromString<SuccessResponse<SessionGrant>>(it).data },
                raw.text,
                "/api/v2/auth/sessions/refresh",
            )
            adopt(grant)
            val token = AccessToken(grant.accessToken, grant.refreshToken)
            mine.complete(token)
            return token
        } catch (exc: Throwable) {
            mine.completeExceptionally(exc)
            // Токен, который сервер перестал принимать, оставлять нельзя: иначе
            // приложение будет бесконечно повторять один и тот же отказ.
            if (exc is ApiException && exc.isAuthenticationFailure) forget()
            throw exc
        } finally {
            refreshMutex.withLock { if (inFlightRefresh === mine) inFlightRefresh = null }
        }
    }

    internal fun parseProblem(text: String): ProblemDetails? = try {
        json.decodeFromString<ProblemDetails>(text)
    } catch (_: Exception) {
        null
    }
}

/** Единый разбор ответа: проблема → ApiException, тело → T. */
internal suspend inline fun <reified T> ApiClient.execute(
    method: HttpMethod,
    path: String,
    authenticated: Boolean = true,
    body: Any? = null,
    noinline block: HttpRequestBuilder.() -> Unit = {},
): T {
    var raw = sendRaw(method, path, authenticated, body, block)
    if (raw.status == HttpStatusCode.Unauthorized.value && authenticated) {
        // 401 означает, что access уже не годится: повторять запрос с ним же
        // бессмысленно. Refresh обязан произойти ДО ретрая, и ровно один раз —
        // если refresh не прошёл, его ошибка и есть ответ для вызывающего.
        refreshSingleFlight(staleAccess = raw.sentAccess)
        raw = sendRaw(method, path, authenticated, body, block)
    }
    if (raw.status >= 400) throwApiException(parseProblem(raw.text), raw.status, raw.text)
    // 204 и пустое тело: возвращаем Unit, чтобы delete() не возился с JSON.
    if (raw.text.isBlank()) return Unit as T
    return decodeOrThrow({ CoreJson.instance.decodeFromString<T>(it) }, raw.text, path)
}

internal suspend inline fun <reified T> ApiClient.get(
    path: String,
    noinline block: HttpRequestBuilder.() -> Unit = {},
): T = execute(HttpMethod.Get, path, authenticated = true, block = block)

internal suspend inline fun <reified T> ApiClient.post(
    path: String,
    body: Any? = null,
    authenticated: Boolean = false,
    noinline block: HttpRequestBuilder.() -> Unit = {},
): T = execute(HttpMethod.Post, path, authenticated, body, block)

internal suspend fun ApiClient.delete(
    path: String,
    block: HttpRequestBuilder.() -> Unit = {},
): Unit = execute<Unit>(HttpMethod.Delete, path, authenticated = true, block = block)

/**
 * POST без приведения к типу ответа.
 *
 * Нужен там, где контракт отдаёт union: `POST /auth/sessions` возвращает либо
 * `SessionGrant`, либо `TwoFaChallenge`, и оба варианта — валидный ответ 200.
 * Приведение «наугад» означало бы, что обычный вход падает на 2FA-аккаунте.
 */
internal suspend fun ApiClient.postRaw(
    path: String,
    body: Any? = null,
    authenticated: Boolean = false,
): RawResponse {
    val raw = sendRaw(HttpMethod.Post, path, authenticated, body) {}
    if (raw.status >= 400) throwApiException(parseProblem(raw.text), raw.status, raw.text)
    return raw
}

