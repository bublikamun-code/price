import Foundation
import SwiftUI
import shared
import UIKit

/// Точка сборки зависимостей.
///
/// Собирается один раз на приложение и живёт столько же: `ApiClient` держит
/// access-токен в памяти, и пересоздавать его на каждый вход в экран означало бы
/// терять ротацию refresh и плодить лишние запросы.
@MainActor
@Observable
final class AppEnvironment {
    let apiClient: ApiClient
    let authRepository: AuthRepository
    let catalogRepository: CatalogRepository
    let mediaBaseURL: URL

    /// Базовый адрес бэкенда. В debug — локальный стенд `make up`, в release —
    /// прод. Значение не должно попадать в репозиторий: прод-адрес придёт
    /// конфигурацией сборки.
    static func makeAPIConfig() -> (baseURL: String, isDev: Bool) {
        let dev = devBaseURL
        if let override = ProcessInfo.processInfo.environment["PRICEWEB_API_BASE_URL"] {
            return (override, override.contains("localhost"))
        }
        #if DEBUG
        return (dev, true)
        #else
        fatalError("PRICEWEB_API_BASE_URL обязателен в release-сборке")
        #endif
    }

    init() {
        let config = Self.makeAPIConfig()
        let baseURL = config.baseURL

        // Движок и вся настройка клиента живут в общем ядре: DSL-конструктор
        // Ktor — это Kotlin-функция с билдером, и Swift её не вызовет. Здесь
        // выбирается только платформа (URLSession, см. KDoc в ядре).
        let ktor = PlatformHttpClient_iosKt.createPlatformHttpClient()

        apiClient = ApiClient(
            baseUrl: baseURL,
            http: ktor,
            // Kotlin не экспортирует значения по умолчанию, поэтому имя сервиса
            // и аккаунта передаются явно: иначе Swift не сможет создать
            // хранилище вообще.
            tokenStore: TokenStore(
                service: "com.priceweb.core.session",
                account: "refresh"
            ),
            device: DeviceInfo(
                deviceName: Self.deviceName,
                osName: "iOS \(ProcessInfo.processInfo.operatingSystemVersionString)",
                appVersion: Self.appVersion
            ),
            // `CoreJson.shared` — обёртка, клиенту нужен её `instance`:
            // это и есть настроенный kotlinx Json.
            json: CoreJson.shared.instance
        )
        authRepository = AuthRepository(api: apiClient)
        catalogRepository = CatalogRepository(api: apiClient)
        // Медиа лежат по относительному пути `/api/v2/media/{id}`, который сам
        // отдаёт байты изображения: клиенту нужен полный URL этого пути.
        mediaBaseURL = URL(string: baseURL) ?? URL(string: Self.devBaseURL)!
    }

    /// Порт API в `infra/docker-compose.yml` задан жёстко (`8000:8000`) и
    /// переопределению `.env` не поддаётся, тогда как порт nginx — да
    /// (`DEV_NGINX_PORT`, на этой машине 8081, и 8080 занят соседним
    /// проектом). Поэтому дефолтом идёт прямой uvicorn: он поднимается всегда.
    ///
    /// Плата за прямой обход nginx — приложение не присылает `X-Forwarded-For`,
    /// и uvicorn считает всех локальных клиентов одним адресом. На симуляторе
    /// это ровно один клиент, так что побочный эффект незаметен; на реальном
    /// устройстве в сети Mac лучше ходить через nginx.
    private static let devBaseURL = "http://localhost:8000"

    private static var appVersion: String {
        Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "0.0.0"
    }

    /// Имя устройства для журнала сессий.
    ///
    /// Берётся `UIDevice.current.model` («iPhone», «iPad») — этого хватает, чтобы
    /// пользователь различал в журнале «iPhone 15 Pro» и «iPad», не выдумывая
    /// данных, которых на телефоне нет.
    private static var deviceName: String { UIDevice.current.model }
}

/// Доступ к окружению из любого экрана.
///
/// Нужен там, где экран получает не сам `ApiClient`, а производные данные:
/// загрузчик картинок должен приложить `Authorization`, а получить токен можно
/// только у ядра.
private struct AppEnvironmentKey: EnvironmentKey {
    static let defaultValue: AppEnvironment? = nil
}

extension EnvironmentValues {
    var appEnvironment: AppEnvironment? {
        get { self[AppEnvironmentKey.self] }
        set { self[AppEnvironmentKey.self] = newValue }
    }
}
