package com.priceweb.core

import io.ktor.client.HttpClient
import io.ktor.client.HttpClientConfig
import io.ktor.client.plugins.HttpTimeout
import io.ktor.client.plugins.contentnegotiation.ContentNegotiation
import io.ktor.serialization.kotlinx.json.json
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlin.time.Duration.Companion.seconds

/**
 * HTTP-клиент, собранный на стороне Kotlin.
 *
 * Существует по одной причине: DSL-конструктор Ktor — это Kotlin-функция с
 * билдером, и Swift её вызвать не может. Если оставить `HttpClient(engine) {
 * expectSuccess = false; install(ContentNegotiation) { json(...) } }` в коде
 * приложения, то весь этот набор правок пришлось бы переписывать на Objective-C
 * вручную — и любое изменение политики клиента (таймаут, ретраи, логирование)
 * снова ложилось бы на две платформы сразу.
 *
 * Смысл противоположен: платформенный слой выбирает движок (URLSession на iOS,
 * OkHttp на Android, CIO на JVM), а всё остальное — общий код.
 */
expect fun createPlatformHttpClient(): HttpClient

/**
 * Настройки, одинаковые на всех платформах.
 *
 * `expectSuccess = false` — обязательное условие работы 401-ветки: Ktor по
 * умолчанию сам бросает исключение на не-2xx, и [ApiClient] не увидел бы тела
 * `ProblemDetails`, из-за чего не смог бы отличить `INVALID_CREDENTIALS` от
 * `RATE_LIMITED` и не смог бы перезапустить refresh.
 *
 * Таймаут общий не из эстетики, а по существу: refresh продлевает grant, и
 * зависший запрос — это refresh-токен, который истечёт, пока приложение ждёт.
 */
fun HttpClientConfig<*>.applyPlatformDefaults() {
    expectSuccess = false
    install(ContentNegotiation) { json(CoreJson.instance) }
    install(HttpTimeout) {
        requestTimeoutMillis = 30.seconds.inWholeMilliseconds
        connectTimeoutMillis = 15.seconds.inWholeMilliseconds
    }
}

/**
 * Главный поток платформы — тот, на котором UI-обновления обязаны приходить.
 *
 * Отдельная функция, потому что `Dispatchers.Main` в Objective-C не
 * экспортируется: Swift видит лишь то, что упомянуто в публичном API ядра, и
 * до `Dispatchers` оттуда не дотянуться. При этом Kotlin не экспортирует
 * значения по умолчанию, поэтому `CatalogPager` из Swift требует диспетчер
 * явно — и единственный способ его получить, не заводя в Swift обёрток на
 * Kotlin-типы, это эта функция.
 */
fun mainUiDispatcher(): CoroutineDispatcher = Dispatchers.Main
