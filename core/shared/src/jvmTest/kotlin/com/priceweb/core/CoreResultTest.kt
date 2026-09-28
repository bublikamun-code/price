package com.priceweb.core

import com.priceweb.core.model.ProblemDetails
import com.priceweb.core.model.SessionGrant
import com.priceweb.core.model.SuccessResponse
import com.priceweb.core.repository.AuthRepository
import com.priceweb.core.repository.CatalogRepository
import com.priceweb.core.session.TokenStore
import io.ktor.client.HttpClient
import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.respond
import io.ktor.client.engine.mock.respondError
import io.ktor.client.plugins.contentnegotiation.ContentNegotiation
import io.ktor.serialization.kotlinx.json.json
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpStatusCode
import io.ktor.http.headersOf
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * Граница между Kotlin-ядром и нативным UI.
 *
 * Проверяется одно свойство, но стоит всего этого файла: **ни один `suspend`-
 * метод ядра не бросает наружу**. Исключение, дошедшее до Objective-C-экспорта,
 * попадает в `Kotlin_ObjCExport_runCompletionFailure` →
 * `terminateWithUnhandledException` → `abort()`: приложение умирает вместо того,
 * чтобы показать «нет связи». На JVM тот же вызов бросил бы наружу, поэтому
 * проверка честная — регресс поймался бы и здесь.
 */
class CoreResultTest {

    @Test
    fun `transport failure becomes a network error instead of an exception`() = runTest {
        val repo = AuthRepository(api(MockEngine { throw java.io.IOException("Connection refused") }))

        val result = repo.currentSession()

        assertFalse(result.isSuccess)
        assertEquals(CoreError.NETWORK_UNAVAILABLE, result.error?.code)
        assertNull(result.value)
        assertTrue(result.error?.message?.isNotBlank() == true)
    }

    @Test
    fun `cancellation from the engine is a network error, not a crash`() = runTest {
        // Именно так ведёт себя движок Ktor на iOS: канал запроса закрывается
        // CancellationException, и без ensureActive() это не отличить от отмены
        // задачи экрана — а отмена задачи дошла бы до Objective-C как abort.
        val repo = AuthRepository(api(MockEngine { throw CancellationException("Channel was closed") }))

        val result = repo.currentSession()

        assertEquals(CoreError.NETWORK_UNAVAILABLE, result.error?.code)
    }

    @Test
    fun `problem json keeps its code and status`() = runTest {
        // Именно вход, а не /session: у аутентифицированного вызова 401 сначала
        // уходит в refresh, и пользователь увидит код отказа самого refresh.
        val repo = AuthRepository(
            api(
                MockEngine {
                    respond(
                        content = Fixtures.raw("problem_invalid_credentials.json"),
                        status = HttpStatusCode.Unauthorized,
                        headers = headersOf(HttpHeaders.ContentType, "application/problem+json"),
                    )
                },
            ),
        )

        val result = repo.login("client@example.by", "Passw0rd!")

        assertEquals("INVALID_CREDENTIALS", result.error?.code)
        assertEquals(401, result.error?.status)
        assertTrue(result.error?.isCredentialsFailure == true)
    }

    @Test
    fun `expired session surfaces as an auth failure, not as a network one`() = runTest {
        val repo = AuthRepository(
            api(
                MockEngine {
                    respond(
                        content = Fixtures.raw("problem_invalid_credentials.json"),
                        status = HttpStatusCode.Unauthorized,
                        headers = headersOf(HttpHeaders.ContentType, "application/problem+json"),
                    )
                },
            ),
        )

        val result = repo.currentSession()

        assertTrue(result.error?.isAuthFailure == true, "гейт должен вернуть на экран входа")
        assertFalse(result.error?.isNetworkFailure == true)
    }

    @Test
    fun `html from a proxy is reported as an unexpected response`() = runTest {
        val repo = CatalogRepository(api(MockEngine { respondError(HttpStatusCode.BadGateway) }))

        val result = repo.facets()

        assertEquals(CoreError.UNEXPECTED_RESPONSE, result.error?.code)
        assertEquals(502, result.error?.status)
    }

    @Test
    fun `payload that does not match the contract is a malformed response`() = runTest {
        val repo = CatalogRepository(
            api(
                MockEngine {
                    respond(
                        content = Fixtures.raw("money.json"),
                        headers = headersOf(HttpHeaders.ContentType, "application/json"),
                    )
                },
            ),
        )

        val result = repo.facets()

        assertEquals(CoreError.MALFORMED_RESPONSE, result.error?.code)
    }

    @Test
    fun `login without a data field is a malformed response`() = runTest {
        val repo = AuthRepository(
            api(
                MockEngine {
                    respond(
                        content = """{"meta":{"requestId":"req-1"}}""",
                        headers = headersOf(HttpHeaders.ContentType, "application/json"),
                    )
                },
            ),
        )

        val result = repo.login("client@example.by", "Passw0rd!")

        assertEquals(CoreError.MALFORMED_RESPONSE, result.error?.code, result.error?.debug)
    }

    @Test
    fun `logout forgets local tokens even when the server is unreachable`() = runTest {
        val store = TokenStore()
        val client = api(MockEngine { throw java.io.IOException("Connection refused") }, store)
        val grant = CoreJson.instance.decodeFromString<SuccessResponse<SessionGrant>>(
            Fixtures.raw("auth_session_grant.json"),
        ).data
        client.adopt(grant)
        assertTrue(store.load() != null, "до выхода токен должен лежать в хранилище")

        val result = AuthRepository(client).logout()

        assertFalse(result.isSuccess)
        assertNull(
            store.load(),
            "локальные токены обязаны стираться даже без сети",
        )
    }

    @Test
    fun `error mapping keeps the problem detail and the real cause`() {
        val problem = ProblemDetails(
            title = "Слишком много попыток",
            status = 429,
            detail = "Подождите минуту",
            code = "RATE_LIMITED",
            requestId = "req-1",
        )
        val error = ApiException(
            code = problem.code!!,
            status = problem.status!!,
            message = problem.detail!!,
            problem = problem,
        ).asCoreError("GET /api/v2/session")

        assertEquals("RATE_LIMITED", error.code)
        assertTrue(error.message.contains("минуту"))
        // 429 — это не отказ авторизации: стирать токены и гнать на экран входа
        // здесь нельзя, пользователь просто подождёт.
        assertFalse(error.isAuthFailure)
    }

    private fun api(engine: MockEngine, store: TokenStore = TokenStore()) = ApiClient(
        baseUrl = "http://test",
        // Тот же клиент, что и на платформе: без ContentNegotiation тело
        // запроса не сериализуется и падает ещё до сети.
        http = HttpClient(engine) {
            expectSuccess = false
            install(ContentNegotiation) { json(CoreJson.instance) }
        },
        tokenStore = store,
        device = DeviceInfo("iPhone", "iOS 18.2", "1.0.0"),
    )
}
