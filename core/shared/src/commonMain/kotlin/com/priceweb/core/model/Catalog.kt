package com.priceweb.core.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull

@Serializable
data class BrandRef(
    val id: String,
    val name: String,
)

@Serializable
data class SeriesRef(
    val id: String,
    val name: String,
    val brandId: String,
)

/**
 * Карточка товара в v2-проекции.
 *
 * [attributes] — свободная карта, заполняемая импортёром CSV, поэтому её
 * значения приходят как `JsonElement`: один и тот же ключ в разных выгрузках
 * может оказаться то строкой, то числом. Строгий тип здесь означил бы, что
 * клиент падает на данных, которые сам же и запросил, — поэтому приводим
 * через [stringAttribute] / [intAttribute], а не через каст в DTO.
 */
@Serializable
data class CatalogProduct(
    val id: String,
    val sku: String,
    val name: String,
    val brand: BrandRef? = null,
    val series: SeriesRef? = null,
    val stockStatus: String,
    val stockQuantity: Int? = null,
    val attributes: Map<String, JsonElement> = emptyMap(),
    val basePrice: Money,
    val retailPrice: Money,
    val clientPrice: Money,
    val exchangeRate: Rate,
    val hasDiscount: Boolean,
    val thumbnail: MediaResource? = null,
    val media: List<MediaResource> = emptyList(),
) {
    /** Значение атрибута как строка; числа и булевы приводятся текстом. */
    fun stringAttribute(key: String): String? {
        val raw = attributes[key] ?: return null
        val primitive = raw as? JsonPrimitive ?: return raw.toString()
        return primitive.contentOrNull
    }

    fun intAttribute(key: String): Int? = when (val raw = attributes[key]) {
        null -> null
        is JsonPrimitive -> raw.intOrNull ?: raw.doubleOrNull?.toInt()
        else -> null
    }
}


@Serializable
data class CatalogFacets(
    val brands: List<BrandRef> = emptyList(),
    val series: List<SeriesRef> = emptyList(),
    val stockStatuses: List<String> = emptyList(),
    val models: List<String> = emptyList(),
)

/**
 * Фильтры страницы каталога.
 *
 * Порядок [brandIds] и [seriesIds] не влияет на выдачу: бэкенд нормализует его
 * при подписи курсора. Не нужно сортировать перед отправкой — но и полагаться
 * на стабильность порядка при слиянии страниц тоже нельзя.
 */
@Serializable
data class CatalogQuery(
    val q: String? = null,
    val brandIds: List<String> = emptyList(),
    val seriesIds: List<String> = emptyList(),
    val stock: String? = null,
    val model: String? = null,
    val sort: String = "name",
    val limit: Int = 50,
) {
    init {
        require(limit in 1..100) { "limit должен быть в диапазоне 1..100 — столько объявляет эндпоинт" }
        require(sort in SORT_VALUES) { "Неизвестная сортировка: $sort" }
    }

    /**
     * Ключ, по которому сбрасывается пагинация. Меняется вместе с фильтрами
     * и сортировкой — ровно тогда, когда курсор от сервера становится непригодным.
     */
    val pageKey: String
        get() = listOf(
            q?.trim().orEmpty(),
            brandIds.sorted().joinToString(","),
            seriesIds.sorted().joinToString(","),
            stock.orEmpty(),
            model?.trim().orEmpty(),
            sort,
        ).joinToString("|")

    companion object {
        const val SORT_NAME = "name"
        const val SORT_NAME_DESC = "-name"
        const val SORT_PRICE = "price"
        const val SORT_PRICE_DESC = "-price"
        const val SORT_SKU = "sku"

        val SORT_VALUES: Set<String> = setOf(
            SORT_NAME,
            SORT_NAME_DESC,
            SORT_PRICE,
            SORT_PRICE_DESC,
            SORT_SKU,
        )
    }
}

/** Режим расчёта цены: фиксированный курс договора или текущий курс НБ РБ. */
@Serializable
enum class PriceCalcMode {
    @SerialName("fixed")
    FIXED,

    @SerialName("nbrb_current")
    NBRB_CURRENT,
}
