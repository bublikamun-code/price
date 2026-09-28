import SwiftUI
import shared

@main
struct PriceWebApp: App {
    @State private var environment = AppEnvironment()

    var body: some Scene {
        WindowGroup {
            RootView(environment: environment)
                .environment(environment)
                .environment(\.appEnvironment, environment)
        }
    }
}

/// Гейт авторизации: восстановление сессии → вход либо каталог.
///
/// Вьюмодели создаются в `init` и кладутся в `@State`, а не строятся прямо в
/// `body`. `body` SwiftUI пересчитывает при каждом изменении состояния, и новый
/// `CatalogViewModel` на каждый проход означал бы новую подписку на пагинацию
/// и потерю уже загруженных страниц — список мигал бы и уезжал в начало.
struct RootView: View {
    let environment: AppEnvironment
    @State private var gate: SessionGate
    @State private var catalogModel: CatalogViewModel
    @State private var loginModel: LoginViewModel

    init(environment: AppEnvironment) {
        self.environment = environment
        _gate = State(
            initialValue: SessionGate(repository: environment.authRepository)
        )
        _catalogModel = State(
            initialValue: CatalogViewModel(repository: environment.catalogRepository)
        )
        _loginModel = State(
            initialValue: LoginViewModel(repository: environment.authRepository)
        )
    }

    var body: some View {
        Group {
            switch gate.state {
            case .restoring:
                ProgressView("Проверяем сессию…")
                    .task { await gate.restore() }
            case .anonymous:
                LoginView(model: loginModel, onAuthenticated: enterSession)
            case .authenticated:
                catalog
            }
        }
    }

    private func enterSession() {
        guard let user = loginModel.authenticatedUser else { return }
        gate.didAuthenticate(user: user)
    }

    private var catalog: some View {
        // Тулбар живого экрана добавляется параметром: `NavigationStack` внутри
        // `CatalogView`, и модификатор `.toolbar` снаружи не находит навигационную
        // панель — кнопка аккаунта просто не отрисовалась бы.
        CatalogView(
            model: catalogModel,
            baseURL: environment.mediaBaseURL
        ) {
            accountMenu
        }
        .id(gate.sessionIdentity)
    }

    private var accountMenu: some View {
        Menu {
            if let user = currentUser {
                Section {
                    Text(user.fullName)
                    Text(user.email)
                    Text("Роль: \(user.role)")
                }
            }
            Section {
                Button("Обновить профиль", systemImage: "arrow.clockwise") {
                    Task { await gate.refresh() }
                }
                Button("Выйти", systemImage: "rectangle.portrait.and.arrow.right", role: .destructive) {
                    Task { await signOut() }
                }
            }
        } label: {
            Image(systemName: "person.crop.circle")
        }
    }

    private func signOut() async {
        await gate.signOut()
        loginModel.reset()
        // Байты фото остались бы в кэше и показались следующему пользователю.
        await ImageCache.shared.removeAll()
    }

    private var currentUser: CurrentUser? {
        if case let .authenticated(user) = gate.state { return user }
        return nil
    }
}
