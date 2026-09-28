package com.priceweb.core

import com.priceweb.core.model.SessionGrant
import com.priceweb.core.model.SuccessResponse
import java.io.File
import kotlinx.datetime.Clock
import kotlinx.serialization.json.Json
import kotlin.time.Duration.Companion.minutes

/**
 * Общие JSON-фикстуры бэкенда — единственный источник правды о контракте.
 *
 * Кодогенератора в проекте нет, поэтому клиентские тесты читают ровно те же
 * файлы, что и `apps/api/tests/test_contract_artifacts.py`. Стоит бэкенду
 * поменять поле — и упадут тесты здесь, а не на устройстве у пользователя.
 */
object Fixtures {
    /** Ищем репозиторий вверх от каталога сборки `core/shared`. */
    private val repoRoot: File by lazy {
        generateSequence(File(".").absoluteFile) { it.parentFile }
            .firstOrNull { File(it, "apps/api/tests/fixtures/v2").isDirectory }
            ?: error("Не найден корень репозитория: ожидается apps/api/tests/fixtures/v2")
    }

    fun raw(name: String): String {
        val file = File(repoRoot, "apps/api/tests/fixtures/v2/$name")
        check(file.isFile) { "Фикстура не найдена: ${file.path}" }
        return file.readText()
    }

    inline fun <reified T> decode(name: String): T =
        CoreJson.instance.decodeFromString(raw(name))

    /**
     * Та же фикстура, но со сроком access-токена, отнесённым от «сейчас».
     *
     * Фикстуры лежат в репозитории с конкретными датами, и `accessTokenExpiresAt`
     * из `auth_session_grant.json` рано или поздно оказывается в прошлом. Для
     * проверки формы контракта это не важно, а для поведения `ApiClient` — очень:
     * просроченный access вызывает проактивный refresh перед каждым запросом, и
     * тест про single-flight падает не из-за гонки, а из-за календаря.
     */
    fun grantWithLiveAccess(): String =
        CoreJson.instance.encodeToString(liveGrantEnvelope())

    /** Тот же grant объектом — для `ApiClient.adopt`, который ждёт не JSON. */
    fun liveGrant(): SessionGrant = liveGrantEnvelope().data

    private fun liveGrantEnvelope(): SuccessResponse<SessionGrant> {
        val envelope = decode<SuccessResponse<SessionGrant>>("auth_session_grant.json")
        return envelope.copy(
            data = envelope.data.copy(
                accessTokenExpiresAt = Clock.System.now() + 15.minutes,
            ),
        )
    }
}
