package com.priceweb.core.repository

import com.priceweb.core.ApiClient
import com.priceweb.core.CoreResult
import com.priceweb.core.get
import com.priceweb.core.guarded
import com.priceweb.core.model.CatalogFacets
import com.priceweb.core.model.CatalogProduct
import com.priceweb.core.model.CatalogQuery
import com.priceweb.core.model.CursorResponse
import com.priceweb.core.model.PriceCalcMode
import com.priceweb.core.model.SuccessResponse
import io.ktor.client.request.parameter
import io.ktor.http.encodeURLPath

/**
 * Имя query-параметра режима цены — ровно `price_calc_mode`, как его объявляет
 * бэкенд (`apps/api/app/api/v2/catalog.py`). Ответы приходят в camelCase,
 * параметры запроса — в snake_case, и FastAPI лишние параметры **молча
 * игнорирует**: опечатка в имени не даёт ни 422, ни записи в лог, а тумблер
 * «НБ РБ (текущий)» молча перестаёт влиять на цены. Регрессия закрыта тестом
 * `CatalogRepositoryTest`, который читает реальные параметры запроса.
 */
private const val PRICE_CALC_MODE_PARAM = "price_calc_mode"

/** Один ответ пагинации: товары плюс признак «есть ещё». */
data class CatalogPage(
    val products: List<CatalogProduct>,
    val nextCursor: String?,
    val hasMore: Boolean,
)

/**
 * Каталог и прайс (`/api/v2/catalog`, раздел products/facets).
 *
 * Всё чтение. Ни корзин, ни заявок в первой версии нативных клиентов нет —
 * методы, которые их создавали бы, здесь появились бы с нарушением §21
 * (документ — потом код), а не раньше.
 *
 * Методы не бросают наружу: см. [CoreResult] — исключение на границе
 * Objective-C убивает процесс, а «каталог не загрузился» должно быть
 * сообщением на экране.
 */
class CatalogRepository(private val api: ApiClient) {

    suspend fun products(
        query: CatalogQuery,
        priceCalcMode: PriceCalcMode = PriceCalcMode.FIXED,
        cursor: String? = null,
    ): CoreResult<CatalogPage> = guarded("GET /api/v2/catalog/products") {
        val response: CursorResponse<CatalogProduct> = api.get("/api/v2/catalog/products") {
            query.q?.takeIf { it.isNotBlank() }?.let { parameter("q", it) }
            query.brandIds.forEach { parameter("brands", it) }
            query.seriesIds.forEach { parameter("series", it) }
            query.stock?.let { parameter("stock", it) }
            query.model?.takeIf { it.isNotBlank() }?.let { parameter("model", it) }
            parameter("sort", query.sort)
            parameter("limit", query.limit)
            parameter(PRICE_CALC_MODE_PARAM, priceCalcMode.wire)
            cursor?.let { parameter("cursor", it) }
        }
        CatalogPage(
            products = response.data,
            nextCursor = response.meta.nextCursor,
            hasMore = response.meta.hasMore,
        )
    }

    suspend fun product(
        id: String,
        priceCalcMode: PriceCalcMode = PriceCalcMode.FIXED,
    ): CoreResult<CatalogProduct> = guarded("GET /api/v2/catalog/products/$id") {
        val response: SuccessResponse<CatalogProduct> =
            api.get("/api/v2/catalog/products/$id") {
                parameter(PRICE_CALC_MODE_PARAM, priceCalcMode.wire)
            }
        response.data
    }

    suspend fun productBySku(
        sku: String,
        priceCalcMode: PriceCalcMode = PriceCalcMode.FIXED,
    ): CoreResult<CatalogProduct> = guarded("GET /api/v2/catalog/products/by-sku/$sku") {
        val response: SuccessResponse<CatalogProduct> =
            // `encodeSlash = true` обязателен: по умолчанию Ktor оставляет слэш
            // разделителем пути, и артикул вида «SKU/42 7» ушёл бы на
            // /products/by-sku/SKU — то есть искал бы не тот товар, а 404
            // выглядел бы как «товара нет».
            api.get(
                "/api/v2/catalog/products/by-sku/${sku.encodeURLPath(encodeSlash = true)}",
            ) {
                parameter(PRICE_CALC_MODE_PARAM, priceCalcMode.wire)
            }
        response.data
    }

    suspend fun facets(): CoreResult<CatalogFacets> = guarded("GET /api/v2/catalog/facets") {
        val response: SuccessResponse<CatalogFacets> = api.get("/api/v2/catalog/facets")
        response.data
    }
}

/** Имя enum в том виде, в каком его ждёт query-параметр. */
private val PriceCalcMode.wire: String
    get() = if (this == PriceCalcMode.FIXED) "fixed" else "nbrb_current"
