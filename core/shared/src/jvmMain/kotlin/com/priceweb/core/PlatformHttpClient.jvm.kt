package com.priceweb.core

import io.ktor.client.HttpClient
import io.ktor.client.engine.cio.CIO

/**
 * Движок для JVM: CIO, родной для Kotlin.
 *
 * Нужен тестам ядра и запуску ядра как обычной библиотеки. В мобильных
 * приложениях JVM-таргет не участвует — там свои actual'ы.
 */
actual fun createPlatformHttpClient(): HttpClient =
    HttpClient(CIO) { applyPlatformDefaults() }
