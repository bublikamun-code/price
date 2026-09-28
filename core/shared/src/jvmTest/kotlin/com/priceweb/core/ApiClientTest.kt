package com.priceweb.core

import com.priceweb.core.get
import com.priceweb.core.model.CatalogProduct
import com.priceweb.core.model.CursorResponse
import com.priceweb.core.model.LoginOutcome
import com.priceweb.core.model.SessionGrant
import com.priceweb.core.model.SessionSnapshot
import com.priceweb.core.model.SessionSummary
import com.priceweb.core.model.SuccessResponse
import com.priceweb.core.model.CurrentUser
import com.priceweb.core.repository.AuthRepository
import com.priceweb.core.session.TokenStore
import io.ktor.client.HttpClient
import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.respond
import io.ktor.client.engine.mock.respondError
import io.ktor.client.plugins.contentnegotiation.ContentNegotiation
import io.ktor.client.request.HttpRequestData
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpStatusCode
import io.ktor.http.headersOf
import io.ktor.http.HttpMethod
import io.ktor.http.encodedPath
import io.ktor.http.ContentType
import io.ktor.serialization.kotlinx.json.json
import java.util.concurrent.atomic.AtomicInteger
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.test.runTest
import kotlinx.datetime.Clock
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNotEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue
import kotlin.time.Duration.Companion.minutes

/**
 * Поведение ApiClient, которое нельзя проверить на фикстурах.
 *
 * Главное здесь — single-flight refresh: если пять экранов одновременно
 * упрутся в 401, refresh должен уйти ровно один раз. Иначе бэкенд увидит
 * цепочку ротаций, где часть запросов переиспользует уже отозванный
 * refresh-токен, и завершит сессию как подозрительную (§16 п.15).
 */
class ApiClientTest {

    private fun grant(
        access: String,
        refresh: String,
        expiresInMinutes: Long = 15,
    ) = SessionGrant(
        accessToken = access,
        accessTokenExpiresAt = Clock.System.now() + expiresInMinutes.minutes,
        refreshToken = refresh,
        refreshTokenExpiresAt = Clock.System.now() + (7 * 24 * 60).minutes,
        session = SessionSummary(
            id = "22222222-2222-4222-8222-222222222222",
            createdAt = Clock.System.now(),
            expiresAt = Clock.System.now() + (7 * 24 * 60).minutes,
            clientType = "NATIVE",
            current = true,
        ),
        user = CurrentUser(
            id = "11111111-1111-4111-8111-111111111111",
            email = "client@example.by",
            fullName = "Иван Клиент",
            role = "CLIENT",
            isActive = true,
            displayCurrency = "BYN",
            consentAccepted = true,
            totpEnabled = false,
            priceDigestEnabled = false,
        ),
    )

    /** Access-токен, который возвращает фикстура grant'а. */
    private val fixtureAccessToken: String =
        Fixtures.decode<SuccessResponse<SessionGrant>>("auth_session_grant.json").data.accessToken

    private fun http(engine: MockEngine) = HttpClient(engine) {
        expectSuccess = false
        install(ContentNegotiation) { json(CoreJson.instance) }
    }

    @Test
    fun `concurrent 401s trigger exactly one refresh and then retry`() = runTest {
        val refreshCalls = AtomicInteger(0)
        val catalogCalls = AtomicInteger(0)
        val engine = MockEngine { request: HttpRequestData ->
            when {
                request.url.encodedPath.endsWith("/auth/sessions/refresh") -> {
                    refreshCalls.incrementAndGet()
                    respond(
                        // Та же фикстура, что проверяет бэкенд: форма grant'а
                        // берётся из контракта, а не из рукописного JSON. Срок
                        // access-токена перенесён на «сейчас» — иначе просрочка
                        // фикстуры добавила бы проактивный refresh к каждому
                        // запросу и сломалала бы подсчёт не из-за гонки.
                        content = Fixtures.grantWithLiveAccess(),
                        headers = headersOf(HttpHeaders.ContentType, "application/json"),
                    )
                }

                request.url.encodedPath.endsWith("/catalog/products") -> {
                    catalogCalls.incrementAndGet()
                    val auth = request.headers[HttpHeaders.Authorization]
                    // Каталог открыт только с тем access-токеном, который вернул
                    // refresh, — сверенным с фикстурой, а не с выдуманной строкой.
                    if (auth != "Bearer $fixtureAccessToken") {
                        respondError(HttpStatusCode.Unauthorized)
                    } else {
                        respond(
                            content = Fixtures.raw("catalog_products_page.json"),
                            headers = headersOf(HttpHeaders.ContentType, "application/json"),
                        )
                    }
                }

                else -> respondError(HttpStatusCode.NotFound)
            }
        }
        val api = ApiClient(
            baseUrl = "http://test",
            http = http(engine),
            tokenStore = TokenStore(),
            device = DeviceInfo("iPhone", "iOS 18.2", "1.0.0"),
        )
        api.adopt(grant("access-old", "refresh-old", expiresInMinutes = 5))

        val results = (1..5).map {
            async {
                api.get<CursorResponse<CatalogProduct>>("/api/v2/catalog/products")
            }
        }.awaitAll()

        assertEquals(1, refreshCalls.get(), "refresh должен уйти ровно один раз")
        assertTrue(results.all { it.data.isNotEmpty() })
        assertEquals(fixtureAccessToken, api.accessToken)
    }

    @Test
    fun `401 for an access token we no longer hold does not spend a second refresh`() = runTest {
        val refreshCalls = AtomicInteger(0)
        val catalogCalls = AtomicInteger(0)
        lateinit var api: ApiClient
        val engine = MockEngine { request: HttpRequestData ->
            when {
                request.url.encodedPath.endsWith("/auth/sessions/refresh") -> {
                    refreshCalls.incrementAndGet()
                    respond(
                        content = Fixtures.grantWithLiveAccess(),
                        headers = headersOf(HttpHeaders.ContentType, "application/json"),
                    )
                }

                else -> {
                    catalogCalls.incrementAndGet()
                    val auth = request.headers[HttpHeaders.Authorization]
                    if (catalogCalls.get() == 1) {
                        // Пока запрос летел, клиент сменил токен — так бывает, когда
                        // refresh завершил кто-то другой. Ответ 401 приходит уже
                        // на устаревший токен.
                        api.adopt(grant(fixtureAccessToken, "refresh-new"))
                        respondError(HttpStatusCode.Unauthorized)
                    } else if (auth == "Bearer $fixtureAccessToken") {
                        respond(
                            content = Fixtures.raw("catalog_products_page.json"),
                            headers = headersOf(HttpHeaders.ContentType, "application/json"),
                        )
                    } else {
                        respondError(HttpStatusCode.Unauthorized)
                    }
                }
            }
        }
        api = ApiClient(
            baseUrl = "http://test",
            http = http(engine),
            tokenStore = TokenStore(),
            device = DeviceInfo("iPhone", "iOS 18.2", "1.0.0"),
        )
        api.adopt(grant("access-old", "refresh-old"))

        val page = api.get<CursorResponse<CatalogProduct>>("/api/v2/catalog/products")

        assertTrue(page.data.isNotEmpty())
        assertEquals(
            0,
            refreshCalls.get(),
            "refresh уже случился, второй раз ходить в сеть незачем",
        )
    }

    @Test
    fun `expired access token is refreshed before the request is sent`() = runTest {
        val refreshCalls = AtomicInteger(0)
        val engine = MockEngine { request ->
            when {
                request.url.encodedPath.endsWith("/auth/sessions/refresh") -> {
                    refreshCalls.incrementAndGet()
                    respond(
                        content = Fixtures.raw("auth_session_grant.json"),
                        headers = headersOf(HttpHeaders.ContentType, "application/json"),
                    )
                }

                else -> respond(
                    content = Fixtures.raw("session_success.json"),
                    headers = headersOf(HttpHeaders.ContentType, "application/json"),
                )
            }
        }
        val api = ApiClient(
            baseUrl = "http://test",
            http = http(engine),
            tokenStore = TokenStore(),
            device = DeviceInfo("iPhone", "iOS 18.2", "1.0.0"),
        )
        // Токен истекает через 30 секунд — меньше минуты запаса, поэтому клиент
        // обновится сам, не дожидаясь 401.
        api.adopt(grant("access-stale", "refresh-old", expiresInMinutes = 0))

        api.get<SuccessResponse<SessionSnapshot>>("/api/v2/session")

        assertEquals(1, refreshCalls.get())
        // Токен подменился на тот, что вернул refresh: значит запрос ушёл с ним.
        assertTrue(api.accessToken != "access-stale")
    }

    @Test
    fun `valid access token for foreign http clients is refreshed when stale`() = runTest {
        val refreshCalls = AtomicInteger(0)
        val engine = MockEngine { request ->
            when {
                request.url.encodedPath.endsWith("/auth/sessions/refresh") -> {
                    refreshCalls.incrementAndGet()
                    respond(
                        content = Fixtures.raw("auth_session_grant.json"),
                        headers = headersOf(HttpHeaders.ContentType, "application/json"),
                    )
                }

                else -> respondError(HttpStatusCode.Unauthorized)
            }
        }
        val api = ApiClient(
            baseUrl = "http://test",
            http = http(engine),
            tokenStore = TokenStore(),
            device = DeviceInfo("iPhone", "iOS 18.2", "1.0.0"),
        )
        api.adopt(grant("access-stale", "refresh-old", expiresInMinutes = 0))

        val token = api.validAccessToken()

        assertEquals(1, refreshCalls.get())
        assertEquals(api.accessToken, token)
        assertNotEquals("access-stale", token, "отдался бы токен, который сервер уже не примет")
    }

    @Test
    fun `valid access token is empty when there is no session at all`() = runTest {
        val engine = MockEngine { respondError(HttpStatusCode.Unauthorized) }
        val api = ApiClient(
            baseUrl = "http://test",
            http = http(engine),
            tokenStore = TokenStore(),
            device = DeviceInfo("iPhone", "iOS 18.2", "1.0.0"),
        )

        // Нативные слои кладут это в `Authorization` без проверки на null,
        // поэтому «нет сессии» должно быть пустой строкой, а не null.
        assertEquals("", api.validAccessToken())
    }

    @Test
    fun `valid access token returns the current one when it is still fresh`() = runTest {
        val refreshCalls = AtomicInteger(0)
        val engine = MockEngine { request ->
            if (request.url.encodedPath.endsWith("/auth/sessions/refresh")) {
                refreshCalls.incrementAndGet()
            }
            respondError(HttpStatusCode.Unauthorized)
        }
        val api = ApiClient(
            baseUrl = "http://test",
            http = http(engine),
            tokenStore = TokenStore(),
            device = DeviceInfo("iPhone", "iOS 18.2", "1.0.0"),
        )
        api.adopt(Fixtures.liveGrant())

        assertEquals(api.accessToken, api.validAccessToken())
        assertEquals(0, refreshCalls.get(), "живой токен обновлять незачем")
    }

    @Test
    fun `refresh rejected with 401 clears tokens and surfaces the problem`() = runTest {
        val engine = MockEngine { request ->
            when {
                request.url.encodedPath.endsWith("/auth/sessions/refresh") ->
                    respond(
                        content = Fixtures.raw("problem_invalid_credentials.json"),
                        status = HttpStatusCode.Unauthorized,
                        headers = headersOf(
                            HttpHeaders.ContentType,
                            "application/problem+json",
                        ),
                    )

                else -> respondError(HttpStatusCode.Unauthorized)
            }
        }
        val store = TokenStore()
        val api = ApiClient(
            baseUrl = "http://test",
            http = http(engine),
            tokenStore = store,
            device = DeviceInfo("iPhone", "iOS 18.2", "1.0.0"),
        )
        api.adopt(grant("access-old", "refresh-old"))

        val failure = assertFailsWith<ApiException> {
            api.get<SuccessResponse<SessionSnapshot>>("/api/v2/session")
        }
        assertEquals("INVALID_CREDENTIALS", failure.code)
        assertTrue(failure.isAuthenticationFailure)
        assertEquals(null, store.load(), "отозванный refresh не должен оставаться в хранилище")
    }

    @Test
    fun `problem json becomes a typed api exception`() = runTest {
        val engine = MockEngine {
            respond(
                content = Fixtures.raw("problem_validation_error.json"),
                status = HttpStatusCode.UnprocessableEntity,
                headers = headersOf(HttpHeaders.ContentType, "application/problem+json"),
            )
        }
        val api = ApiClient(
            baseUrl = "http://test",
            http = http(engine),
            tokenStore = TokenStore(),
            device = DeviceInfo("iPhone", "iOS 18.2", "1.0.0"),
        )
        val failure = assertFailsWith<ApiException> {
            api.post<SuccessResponse<SessionGrant>>("/x")
        }
        assertEquals("VALIDATION_ERROR", failure.code)
        assertEquals(422, failure.status)
        assertEquals("v2-fixture-validation-001", failure.requestId)
    }

    @Test
    fun `non problem error body is reported as unexpected`() = runTest {
        val engine = MockEngine {
            respond(
                content = "<html>502 Bad Gateway</html>",
                status = HttpStatusCode.BadGateway,
                headers = headersOf(HttpHeaders.ContentType, "text/html"),
            )
        }
        val api = ApiClient(
            baseUrl = "http://test",
            http = http(engine),
            tokenStore = TokenStore(),
            device = DeviceInfo("iPhone", "iOS 18.2", "1.0.0"),
        )
        assertFailsWith<UnexpectedResponseException> {
            api.post<SuccessResponse<SessionGrant>>("/x")
        }
    }

    @Test
    fun `login without 2fa adopts grant and returns granted outcome`() = runTest {
        val engine = MockEngine { request ->
            assertEquals(HttpMethod.Post, request.method)
            assertEquals("/api/v2/auth/sessions", request.url.encodedPath)
            val sent = (request.body as io.ktor.http.content.TextContent).text
            // Метаданные устройства обязаны уехать с первого запроса: сессия
            // создаётся именно здесь, второго шанса передать их нет.
            assertTrue(sent.contains("\"clientType\":\"NATIVE\""))
            assertTrue(sent.contains("\"deviceName\":\"iPhone 15 Pro\""))
            assertTrue(sent.contains("\"os\":\"iOS 18.2\""))
            respond(
                content = Fixtures.raw("auth_session_grant.json"),
                headers = headersOf(HttpHeaders.ContentType, ContentType.Application.Json.toString()),
            )
        }
        val store = TokenStore()
        val api = ApiClient(
            baseUrl = "http://test",
            http = http(engine),
            tokenStore = store,
            device = DeviceInfo("iPhone 15 Pro", "iOS 18.2", "1.0.0"),
        )

        val outcome = AuthRepository(api).login("client@example.by", "Passw0rd!")

        assertNull(outcome.error)
        val granted = outcome.value
        assertTrue(granted is LoginOutcome.Granted)
        val grant = (granted as LoginOutcome.Granted).grant
        assertEquals("fixture-refresh-token-0001", grant.refreshToken)
        assertEquals(grant.refreshToken, store.load()?.refreshToken)
    }

    @Test
    fun `login with 2fa returns challenge and stores nothing`() = runTest {
        val engine = MockEngine {
            respond(
                content = Fixtures.raw("auth_two_fa_challenge.json"),
                headers = headersOf(HttpHeaders.ContentType, ContentType.Application.Json.toString()),
            )
        }
        val store = TokenStore()
        val api = ApiClient(
            baseUrl = "http://test",
            http = http(engine),
            tokenStore = store,
            device = DeviceInfo("iPhone 15 Pro", "iOS 18.2", "1.0.0"),
        )

        val outcome = AuthRepository(api).login("client@example.by", "Passw0rd!")

        assertNull(outcome.error)
        val twoFa = outcome.value
        assertTrue(twoFa is LoginOutcome.TwoFaRequired)
        val challenge = (twoFa as LoginOutcome.TwoFaRequired).challenge
        assertTrue(challenge.twoFaRequired)
        assertTrue(challenge.ticket.isNotEmpty())
        assertEquals(null, store.load(), "до подтверждения кода токенов быть не должно")
    }
}
