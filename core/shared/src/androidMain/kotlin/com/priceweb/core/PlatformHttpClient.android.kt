package com.priceweb.core

import io.ktor.client.HttpClient
import io.ktor.client.engine.okhttp.OkHttp

/**
 * Движок для Android: OkHttp.
 *
 * OkHttp, а не CIO, потому что на Android у клиента есть системный
 * `NetworkSecurityConfig` и пул TLS-сессий OkHttp, который делится с WebView
 * приложения; свой стек означал бы вторую независимую настройку.
 *
 * ⚠️ Этот файл написан, но **не проверен компиляцией**: Android SDK на машине
 * сборки не установлен, а `enableAndroid` выключен, поэтому
 * `compileKotlinAndroid` никогда не запускался. Первая сборка Android
 * (см. `android/README.md`) обязана начинаться с неё, а не с установки в
 * store.
 */
actual fun createPlatformHttpClient(): HttpClient =
    HttpClient(OkHttp) { applyPlatformDefaults() }
