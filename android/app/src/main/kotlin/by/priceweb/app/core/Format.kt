package by.priceweb.app.core

import com.priceweb.core.model.CatalogProduct
import com.priceweb.core.model.Money
import com.priceweb.core.model.Rate
import java.math.BigDecimal
import java.math.RoundingMode
import java.text.NumberFormat

/**
 * Разбор денежной строки контракта.
 *
 * `Money.amount` приходит строкой («294.90»). `Double` здесь дал бы «294,9» и
 * разъезжающиеся копейки в итоговой сумме, поэтому разбор идёт через
 * `BigDecimal` — ровно так же, как на iOS.
 */
fun Money.amountAsDecimal(): BigDecimal? = decimal(amount)

private fun decimal(raw: String): BigDecimal? = runCatching {
    BigDecimal(raw)
}.getOrNull()

/** «294,90 BYN» — с локальным разделителем, но без изменения величины. */
val Money.displayAmount: String
    get() = "${displayNumber} $currency"

/** Число без валюты — для мест, где валюта подписана один раз. */
val Money.displayNumber: String
    get() = amountAsDecimal()?.let { formatter().format(it) } ?: amount

/**
 * Курс ровно с тем числом знаков, которое объявил бэкенд в `Rate.scale`.
 *
 * На проводе `value` — строка («12.5000»), а `scale` говорит, сколько знаков
 * после запятой значащих. Доверять одной строке нельзя: она приходит из
 * Python и может оказаться «12.5» при `scale = 4`, и экран, который умножит
 * на неё сумму, покажет курс, которого нет.
 */
val Rate.displayValue: String
    get() {
        val places = scale
        if (places <= 0) return value
        val parsed = decimal(value) ?: return value
        val normalized = parsed.setScale(places, RoundingMode.HALF_UP)
        return formatter(normalized.scale()).format(normalized)
    }

/** [formatter] с явным числом знаков: у [BigDecimal] он свой, у [Money] — всегда два. */
private fun formatter(fractionDigits: Int = 2): NumberFormat =
    NumberFormat.getNumberInstance().apply {
        minimumFractionDigits = fractionDigits
        maximumFractionDigits = fractionDigits
    }

/** Цена, которую видит клиент: персональная, если она есть. */
val CatalogProduct.displayPrice: Money
    get() = if (hasDiscount) clientPrice else retailPrice

/** Человекочитаемый остаток: количество бессмысленно, если статус «под заказ». */
val CatalogProduct.stockDisplay: String
    get() = when (stockStatus) {
        "IN_STOCK" -> stockQuantity?.takeIf { it > 0 }?.let { "В наличии: $it" } ?: "В наличии"
        "PREORDER" -> "Под заказ"
        else -> stockStatus
    }

val CatalogProduct.isInStock: Boolean
    get() = stockStatus == "IN_STOCK"

/** Ключи атрибутов импортёра приходят snake_case — для экрана это читаемее. */
fun String.humanize(): String =
    replace('_', ' ').replace('-', ' ').trim()
