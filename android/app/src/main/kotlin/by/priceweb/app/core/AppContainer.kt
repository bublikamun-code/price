package by.priceweb.app.core

import com.priceweb.core.ApiClient
import com.priceweb.core.CoreJson
import com.priceweb.core.DeviceInfo
import com.priceweb.core.createPlatformHttpClient
import com.priceweb.core.repository.AuthRepository
import com.priceweb.core.repository.CatalogRepository
import com.priceweb.core.session.TokenStore

/**
 * Сборка зависимостей приложения.
 *
 * Аналог `AppEnvironment` на iOS: единственное место, где известно, каким
 * HTTP-клиентом мы ходим на сервер и где лежат токены.
 */
class AppContainer(baseUrl: String, appVersion: String) {
    val baseUrl: String = baseUrl.trimEnd('/')

    val apiClient: ApiClient

    val authRepository: AuthRepository

    val catalogRepository: CatalogRepository

    /** Токен для запросов мимо Ktor — прежде всего картинок Coil. */
    val sessionTokenProvider: SessionTokenProvider

    init {
        check(baseUrl.isNotBlank()) {
            "API_BASE_URL пуст — приложение не знает, куда ходить. " +
                "Передайте -Ppriceweb.apiBaseUrl=... при сборке."
        }

        // HTTP-клиент собирает ядро, а не приложение. Своя сборка здесь была бы
        // не «гибкостью», а расхождением с ApiClient: у ядра ветка 401 держится
        // на expectSuccess = false, и клиент с умолчанием Ktor (true) бросил бы
        // исключение раньше, чем тело problem+json удалось бы прочитать, — то
        // есть refresh-token не обновлялся бы никогда.
        val http = createPlatformHttpClient()

        apiClient = ApiClient(
            baseUrl = baseUrl,
            http = http,
            tokenStore = TokenStore(),
            device = DeviceInfo(
                deviceName = android.os.Build.MODEL,
                osName = "Android ${android.os.Build.VERSION.RELEASE}",
                appVersion = appVersion,
            ),
            json = CoreJson.instance,
        )
        authRepository = AuthRepository(apiClient)
        catalogRepository = CatalogRepository(apiClient)
        sessionTokenProvider = SessionTokenProvider(apiClient)
    }

    /** Полный URL медиа-ресурса: `url` в контракте — путь от корня API. */
    fun mediaUrl(path: String): String = baseUrl + path
}
