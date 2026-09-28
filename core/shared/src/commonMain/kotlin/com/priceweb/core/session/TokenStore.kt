package com.priceweb.core.session

import com.priceweb.core.model.SessionGrant

/**
 * Хранилище пары токенов.
 *
 * Объявлено `expect` в общем коде и реализуется отдельно на каждой платформе:
 * iOS — Keychain, Android — EncryptedSharedPreferences. Общий код обязан
 * обращаться только через этот интерфейс и никогда — к файлам или SharedPreferences
 * напрямую, иначе iOS-реализация получит доступ к незашифрованным копиям токенов.
 *
 * Контракт хранения: refresh-токен лежит в защищённом хранилище, access-токен
 * можно держать в памяти процесса — он живёт 15 минут и переживать перезапуск
 * приложения ему не нужно.
 *
 * Хранилище — внутренность ядра, вызывать его из SwiftUI нельзя: `suspend`
 * пересекает границу Objective-C, а бросок там убивает процесс (см.
 * `CoreResult` в `com.priceweb.core`). Нативный слой получает токены только
 * через `ApiClient`.
 */
expect class TokenStore {
    /**
     * Возвращает сохранённый grant, если он есть.
     * Реализация обязана вернуть `null`, а не бросать исключение, если хранилище
     * недоступно: «нет токена» — это штатное состояние гостя, а не ошибка.
     */
    suspend fun load(): SessionGrant?

    suspend fun save(grant: SessionGrant)

    /** Отзыв сессии на сервере выполнит вызывающий; здесь только локальная зачистка. */
    suspend fun clear()
}

/** Токены, которые ApiClient держит в памяти на время работы процесса. */
data class AccessToken(val value: String, val refreshToken: String)
