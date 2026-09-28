import Foundation
import shared

/// Состояние экрана входа.
///
/// Держится на `@Observable`, а не на отдельном редьюсере: состояния тут три,
/// а логика переходов между ними помещается в один метод.
@MainActor
@Observable
final class LoginViewModel {
    enum Phase: Equatable {
        case credentials
        case twoFactor(ticket: String)
    }

    private let repository: AuthRepository

    var email = ""
    var password = ""
    var code = ""
    var phase: Phase = .credentials
    var isSubmitting = false
    var errorMessage: String?

    /// Кто вошёл — из ответа сервера, без дополнительного запроса.
    ///
    /// Ответ на вход уже содержит пользователя, поэтому спрашивать
    /// `/api/v2/session` сразу после успеха — лишний round-trip на каждом
    /// старте приложения. Гейт берёт профиль отсюда.
    private(set) var authenticatedUser: CurrentUser?

    init(repository: AuthRepository) {
        self.repository = repository
    }

    var canSubmitCredentials: Bool {
        !isSubmitting && email.contains("@") && password.count >= 8
    }

    var canSubmitCode: Bool {
        !isSubmitting && code.count >= 6
    }

    /// Вход. Возвращает `true`, если сессия получена и 2FA не потребовалась.
    @discardableResult
    func submitCredentials() async -> Bool {
        guard canSubmitCredentials else { return false }
        isSubmitting = true
        errorMessage = nil
        defer { isSubmitting = false }

        do {
            // Kotlin отдаёт `(CoreResult<LoginOutcome>?, Error?)`, а не `Result`:
            // значение nullable, поэтому мост двухаргументный — withKmpValue.
            let result: CoreResult<LoginOutcome> = try await withKmpValue { completion in
                self.repository.login(
                    email: self.email,
                    password: self.password,
                    completionHandler: completion
                )
            }
            let outcome = try value(of: result)
            // `LoginOutcome` — протокол, а sealed-классы лежат рядом с ним
            // своими типами, а не вложенными (`LoginOutcome.Granted` не
            // существует — проверено по сгенерированному shared.h).
            if let granted = outcome as? LoginOutcomeGranted {
                authenticatedUser = granted.grant.user
                return true
            }
            if let challenge = outcome as? LoginOutcomeTwoFaRequired {
                phase = .twoFactor(ticket: challenge.challenge.ticket)
                return false
            }
            errorMessage = "Сервер вернул неожиданный ответ на вход."
            return false
        } catch {
            errorMessage = userFacingMessage(error)
            return false
        }
    }

    func submitCode() async -> Bool {
        guard case let .twoFactor(ticket) = phase, canSubmitCode else { return false }
        isSubmitting = true
        errorMessage = nil
        defer { isSubmitting = false }

        do {
            let result: CoreResult<SessionGrant> = try await withKmpValue { completion in
                self.repository.verifyTwoFa(
                    ticket: ticket,
                    code: self.code,
                    completionHandler: completion
                )
            }
            authenticatedUser = try value(of: result).user
            return true
        } catch {
            // Неверный код не должен сбрасывать поле: пользователь имеет право
            // исправить его, не начиная вход заново.
            errorMessage = userFacingMessage(error)
            code = ""
            return false
        }
    }

    /// Очистка формы при выходе из аккаунта.
    ///
    /// Вьюмодель живёт дольше одного сеанса (она в `@State` гейта), поэтому без
    /// сброса следующий вход начинался бы с чужих почты и кода в поле.
    func reset() {
        email = ""
        password = ""
        code = ""
        phase = .credentials
        isSubmitting = false
        errorMessage = nil
        authenticatedUser = nil
    }

    func backToCredentials() {
        phase = .credentials
        code = ""
        errorMessage = nil
    }
}
