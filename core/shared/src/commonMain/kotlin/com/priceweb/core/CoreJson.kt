package com.priceweb.core

import kotlinx.serialization.json.Json

/**
 * Общий инстанс JSON для всех нативных клиентов.
 *
 * `ignoreUnknownKeys` — обязателен, а не ленивость: клиент может быть новее
 * сервера (или наоборот), и новое поле в ответе не должно ронять приложение.
 * `explicitNulls = false` нужен, чтобы отличать «поле отсутствует» от «поле null»
 * там, где это разные состояния, например `series: null` в карточке товара.
 */
object CoreJson {
    val instance: Json = Json {
        ignoreUnknownKeys = true
        explicitNulls = false
        isLenient = false
        coerceInputValues = false
        // Отправляем все поля, включая равные значению по умолчанию. Иначе
        // clientType="NATIVE" просто не ушёл бы на провод, и клиент стал бы
        // зависеть от того, что сервер по умолчанию тоже NATIVE. Смена дефолта
        // на стороне сервера тихо превратила бы нативный вход в браузерный.
        encodeDefaults = true
    }
}
