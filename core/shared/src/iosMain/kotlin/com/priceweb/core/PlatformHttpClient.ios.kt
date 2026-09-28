package com.priceweb.core

import io.ktor.client.HttpClient
import io.ktor.client.engine.darwin.Darwin

/**
 * Движок для iOS: URLSession.
 *
 * Darwin, а не CIO, потому что App Store Review смотрит в трафик приложения:
 * собственный TLS-стек на NSURLSession снимает вопрос «откуда тут шифрование»,
 * а CIO на iOS всё равно уходит в стороннюю сетевую реализацию поверх
 * Security.framework с лишним риском, что её откажут.
 */
actual fun createPlatformHttpClient(): HttpClient =
    HttpClient(Darwin) { applyPlatformDefaults() }
