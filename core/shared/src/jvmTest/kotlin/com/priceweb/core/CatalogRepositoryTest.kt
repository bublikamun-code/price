package com.priceweb.core

import com.priceweb.core.model.CatalogQuery
import com.priceweb.core.model.PriceCalcMode
import com.priceweb.core.repository.CatalogRepository
import com.priceweb.core.session.TokenStore
import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.respond
import io.ktor.client.engine.mock.respondError
import io.ktor.client.request.HttpRequestData
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpStatusCode
import io.ktor.http.headersOf
import java.util.concurrent.atomic.AtomicReference
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * Имена query-параметров, в которых каталог может ошибиться незаметно.
 *
 * FastAPI лишние параметры **молча игнорирует**: опечатка в имени не даёт ни
 * 422, ни записи в лог, а тумблер «НБ РБ (текущий)» просто перестаёт влиять на
 * цены. Поэтому тест читает настоящий URL, который ушёл в сеть, а не проверяет
 * внутреннее состояние репозитория.
 */
class CatalogRepositoryTest {

    private fun http(engine: MockEngine) = io.ktor.client.HttpClient(engine) {
        expectSuccess = false
    }

    private fun api(engine: MockEngine) = ApiClient(
        baseUrl = "http://test",
        http = http(engine),
        tokenStore = TokenStore(),
        device = DeviceInfo("iPhone", "iOS 18.2", "1.0.0"),
    )

    @Test
    fun `list sends price_calc_mode in snake_case with the wire value`() = runTest {
        val seen = AtomicReference<io.ktor.http.Url?>(null)
        val engine = MockEngine { request: HttpRequestData ->
            seen.set(request.url)
            respond(
                content = Fixtures.raw("catalog_products_page.json"),
                headers = headersOf(HttpHeaders.ContentType, "application/json"),
            )
        }

        CatalogRepository(api(engine)).products(
            query = CatalogQuery(q = "дрель"),
            priceCalcMode = PriceCalcMode.NBRB_CURRENT,
        )

        val url = seen.get()!!
        assertEquals("nbrb_current", url.parameters["price_calc_mode"])
        assertEquals("дрель", url.parameters["q"])
        // Именно этот тест поймал опечатку в имени параметра: response-DTO
        // приходят в camelCase, и рукавка «priceCalcMode» выглядит законно.
        assertTrue(
            url.parameters.names().none { it == "priceCalcMode" },
            "camelCase-имя параметра FastAPI игнорирует молча",
        )
    }

    @Test
    fun `fixed mode is sent as the word fixed not as the enum name`() = runTest {
        val seen = AtomicReference<io.ktor.http.Url?>(null)
        val engine = MockEngine { request: HttpRequestData ->
            seen.set(request.url)
            respond(
                content = Fixtures.raw("catalog_products_page.json"),
                headers = headersOf(HttpHeaders.ContentType, "application/json"),
            )
        }

        CatalogRepository(api(engine)).products(query = CatalogQuery())

        assertEquals("fixed", seen.get()!!.parameters["price_calc_mode"])
    }

    @Test
    fun `product card and by-sku lookup also send price_calc_mode`() = runTest {
        val urls = mutableListOf<io.ktor.http.Url>()
        val engine = MockEngine { request: HttpRequestData ->
            urls += request.url
            respond(
                content = Fixtures.raw("catalog_product_detail.json"),
                headers = headersOf(HttpHeaders.ContentType, "application/json"),
            )
        }
        val repo = CatalogRepository(api(engine))

        repo.product(id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", priceCalcMode = PriceCalcMode.NBRB_CURRENT)
        repo.productBySku(sku = "SKU/42 7", priceCalcMode = PriceCalcMode.NBRB_CURRENT)

        // Обе карточки обязаны нести режим цены: без него они вернули бы цены
        // по договору, и тумблер на экране прайса выглядел бы сломанным.
        assertEquals(2, urls.size)
        assertTrue(urls.all { it.parameters["price_calc_mode"] == "nbrb_current" })
    }

    @Test
    fun `sku with a slash is encoded into the path instead of splitting the route`() = runTest {
        val seen = AtomicReference<io.ktor.http.Url?>(null)
        val engine = MockEngine { request: HttpRequestData ->
            seen.set(request.url)
            respondError(HttpStatusCode.NotFound)
        }
        val repo = CatalogRepository(api(engine))

        // 404 ожидаем: интересует только URL, до которого дошёл запрос.
        repo.productBySku(sku = "SKU/42 7")

        // Неэкранированный слэш увёл бы запрос на /catalog/products/by-sku/SKU
        // и поиск по SKU сломался бы ровно на тех артикулах, где есть «/».
        val path = seen.get()!!.encodedPath
        assertEquals("/api/v2/catalog/products/by-sku/SKU%2F42%207", path)
    }
}
