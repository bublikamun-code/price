import Foundation
import shared

/// Состояние приложения верхнего уровня: залогинен или нет.
@MainActor
@Observable
final class SessionGate {
    enum State {
        case restoring
        case anonymous
        case authenticated(CurrentUser)
    }

    private let repository: AuthRepository

    var state: State = .restoring

    /// Идентичность сеанса — для сброса экранов при смене пользователя.
    ///
    /// Каталог помнит загруженные страницы и выбранные фильтры. После выхода и
    /// входа под другим аккаунтом это уже чужие данные, поэтому экран надо
    /// пересоздать, а не показать прошлый список.
    var sessionIdentity: String? {
        if case let .authenticated(user) = state { return user.id }
        return nil
    }

    init(repository: AuthRepository) {
        self.repository = repository
    }

    /// Проверка сохранённой сессии при запуске.
    ///
    /// Токен лежит в Keychain, поэтому после перезапуска приложение может
    /// остаться «залогиненным» без повторного входа. Но хранилище могло
    /// остаться с протухшим refresh, поэтому граница доверия здесь одна:
    /// спрашиваем сервер.
    ///
    /// Отказ любого вида ведёт к экрану входа: без подтверждённого профиля
    /// каталог показать нечем, а «нет связи» на экране входа выглядит честнее,
    /// чем пустой каталог без объяснения. Сама причина остаётся в
    /// [LoginViewModel] — она покажет её на первой попытке входа.
    func restore() async {
        state = .restoring
        let snapshot = try? await fetchSession()
        state = snapshot.map { State.authenticated($0.user) } ?? .anonymous
    }

    /// Вход состоялся: профиль берём из ответа на вход, а не спрашиваем заново.
    ///
    /// Раньше здесь стоял `refresh()`, и каждый вход стоил лишнего обращения к
    /// `/api/v2/session` за данными, которые сервер только что вернул в grant.
    func didAuthenticate(user: CurrentUser) {
        state = .authenticated(user)
    }

    func refresh() async {
        let snapshot = try? await fetchSession()
        state = snapshot.map { State.authenticated($0.user) } ?? .anonymous
    }

    func signOut() async {
        // Выход на сервере может не пройти (нет сети, сервер недоступен) —
        // локальные токены всё равно стираются внутри репозитория, поэтому
        // пользователь не должен сидеть в приложении с мёртвой сессией.
        try? await withKmpValue { completion in
            repository.logout(completionHandler: completion)
        }
        state = .anonymous
    }

    private func fetchSession() async throws -> SessionSnapshot {
        let result: CoreResult<SessionSnapshot> = try await withKmpValue { completion in
            repository.currentSession(completionHandler: completion)
        }
        return try value(of: result)
    }
}
