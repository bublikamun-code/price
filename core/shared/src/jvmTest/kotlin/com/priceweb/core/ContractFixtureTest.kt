package com.priceweb.core

import com.priceweb.core.model.CatalogFacets
import com.priceweb.core.model.CatalogProduct
import com.priceweb.core.model.CursorResponse
import com.priceweb.core.model.Money
import com.priceweb.core.model.Rate
import com.priceweb.core.model.SessionGrant
import com.priceweb.core.model.SessionSnapshot
import com.priceweb.core.model.SessionSummary
import com.priceweb.core.model.SuccessResponse
import com.priceweb.core.model.TwoFaChallenge
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * Клиентские тесты на общих фикстурах бэкенда.
 *
 * Это единственная доступная сейчас проверка контракта мобильных клиентов:
 * тулчейна для iOS/Android на машине нет, а фикстуры — тот же артефакт, который
 * валидируется пидantic-ом в `test_contract_artifacts.py`. Поменяет бэкенд DTO —
 * упадёт здесь.
 */
class ContractFixtureTest {

    @Test
    fun `money and rate keep fixed decimal strings`() {
        val money = Fixtures.decode<Money>("money.json")
        assertEquals("294.90", money.amount)
        assertEquals("BYN", money.currency)

        val rate = Fixtures.decode<Rate>("rate.json")
        assertEquals("1.0000", rate.value)
        assertEquals(4, rate.scale)
    }

    @Test
    fun `session grant decodes with camelCase tokens and device metadata`() {
        val grant = Fixtures.decode<SuccessResponse<SessionGrant>>(
            "auth_session_grant.json",
        ).data

        assertEquals("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.fixture-access", grant.accessToken)
        assertEquals("fixture-refresh-token-0001", grant.refreshToken)
        assertEquals("2026-09-27T12:15:00Z", grant.accessTokenExpiresAt.toString())
        assertEquals("iPhone 15 Pro", grant.session.deviceName)
        assertEquals("iOS 18.2", grant.session.osName)
        assertEquals("NATIVE", grant.session.clientType)
        assertTrue(grant.session.current)
        assertEquals("client@example.by", grant.user.email)
        assertEquals("BYN", grant.user.displayCurrency)
    }

    @Test
    fun `two fa challenge decodes without tokens`() {
        val challenge = Fixtures.decode<SuccessResponse<TwoFaChallenge>>(
            "auth_two_fa_challenge.json",
        ).data

        assertTrue(challenge.twoFaRequired)
        assertTrue(challenge.ticket.isNotEmpty())
    }

    @Test
    fun `session journal keeps web entries without device metadata`() {
        val sessions = Fixtures.decode<SuccessResponse<List<SessionSummary>>>(
            "auth_sessions_journal.json",
        ).data

        assertEquals(2, sessions.size)
        assertTrue(sessions[0].current)
        assertEquals("NATIVE", sessions[0].clientType)
        assertTrue(!sessions[1].current)
        assertEquals("WEB", sessions[1].clientType)
        // У браузера нет «имени устройства» — сервер не должен его выдумывать.
        assertNull(sessions[1].deviceName)
        assertNull(sessions[1].osName)
    }

    @Test
    fun `current session snapshot decodes`() {
        val snapshot = Fixtures.decode<SuccessResponse<SessionSnapshot>>(
            "session_success.json",
        ).data
        assertEquals("USER", snapshot.commercialScope)
        assertNull(snapshot.organizationId)
        assertTrue(snapshot.memberships.isEmpty())
    }

    @Test
    fun `catalog page decodes thumbnail and media`() {
        val page = Fixtures.decode<CursorResponse<CatalogProduct>>("catalog_products_page.json")
        val product = page.data.single()

        assertEquals("V2-FIXTURE-1", product.sku)
        assertEquals("100.00", product.basePrice.amount)
        assertEquals("90.00", product.clientPrice.amount)
        assertTrue(product.hasDiscount)
        assertTrue(product.media.isEmpty())

        val thumbnail = requireNotNull(product.thumbnail)
        assertEquals(400, thumbnail.width)
        assertEquals("image/webp", thumbnail.mimeType)
        // url стабильный и ведёт на v2-эндпоинт, а не на presigned S3.
        assertEquals("/api/v2/media/${thumbnail.id}", thumbnail.url)
        assertTrue(!thumbnail.url.contains("X-Amz-Signature"))
    }

    @Test
    fun `product detail decodes gallery with distinct dimensions`() {
        val detail = Fixtures.decode<SuccessResponse<CatalogProduct>>(
            "catalog_product_detail.json",
        ).data

        assertEquals(2, detail.media.size)
        assertEquals(1200, detail.media[0].width)
        assertEquals(1200, detail.media[0].height)
        assertEquals(900, detail.media[1].height)
        assertEquals("Fixture Series", detail.series?.name)
    }

    @Test
    fun `attributes survive as json elements`() {
        val detail = Fixtures.decode<SuccessResponse<CatalogProduct>>(
            "catalog_product_detail.json",
        ).data

        assertEquals("Аксессуары", detail.stringAttribute("model"))
        assertNull(detail.stringAttribute("missing"))
        assertNull(detail.intAttribute("model"))
    }

    @Test
    fun `facets decode`() {
        val facets = Fixtures.decode<SuccessResponse<CatalogFacets>>("catalog_facets.json").data
        assertEquals("Fixture Brand", facets.brands.single().name)
        assertEquals(listOf("IN_STOCK"), facets.stockStatuses)
        assertEquals(listOf("Аксессуары"), facets.models)
    }

    @Test
    fun `problem details map to typed codes`() {
        val invalid = Fixtures.decode<com.priceweb.core.model.ProblemDetails>(
            "problem_invalid_credentials.json",
        )
        assertEquals("INVALID_CREDENTIALS", invalid.code)
        assertEquals(401, invalid.status)
        assertEquals("v2-fixture-auth-problem-001", invalid.requestId)

        val validation = Fixtures.decode<com.priceweb.core.model.ProblemDetails>(
            "problem_validation_error.json",
        )
        assertEquals("VALIDATION_ERROR", validation.code)
        assertEquals(1, validation.errors.size)
        assertEquals("orderId", validation.errors[0].field)
    }

    @Test
    fun `decoding a mismatched payload fails loudly`() {
        // Страховка от «тесты зелёные, потому что декодер молчит»: если бы
        // DTO разъехался с фикстурой, здесь было бы исключение, а не пустой объект.
        assertFailsWith<Exception> {
            CoreJson.instance.decodeFromString<SessionGrant>(Fixtures.raw("money.json"))
        }
    }
}
