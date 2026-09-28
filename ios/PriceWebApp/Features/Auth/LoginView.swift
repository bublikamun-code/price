import SwiftUI

/// Вход: почта + пароль, и — если у клиента включена 2FA — проверка кода.
struct LoginView: View {
    @Bindable var model: LoginViewModel
    let onAuthenticated: () -> Void

    var body: some View {
        NavigationStack {
            Form {
                switch model.phase {
                case .credentials:
                    credentials
                case .twoFactor:
                    twoFactor
                }
            }
            .navigationTitle("Вход")
        }
    }

    private var credentials: some View {
        Section {
            TextField("Почта", text: $model.email)
                .textContentType(.username)
                .keyboardType(.emailAddress)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()

            SecureField("Пароль", text: $model.password)
                .textContentType(.password)

            Button {
                Task {
                    if await model.submitCredentials() { onAuthenticated() }
                }
            } label: {
                if model.isSubmitting {
                    ProgressView().frame(maxWidth: .infinity)
                } else {
                    Text("Войти").frame(maxWidth: .infinity)
                }
            }
            .disabled(!model.canSubmitCredentials)
        } footer: {
            if let error = model.errorMessage {
                Label(error, systemImage: "exclamationmark.triangle")
                    .foregroundStyle(.red)
            }
        }
    }

    private var twoFactor: some View {
        Section {
            Text("Введите код из приложения-аутентификатора")
                .font(.callout)
                .foregroundStyle(.secondary)

            TextField("Код", text: $model.code)
                .keyboardType(.numberPad)
                .textContentType(.oneTimeCode)
                .font(.title2.monospacedDigit())

            Button {
                Task {
                    if await model.submitCode() { onAuthenticated() }
                }
            } label: {
                if model.isSubmitting {
                    ProgressView().frame(maxWidth: .infinity)
                } else {
                    Text("Подтвердить").frame(maxWidth: .infinity)
                }
            }
            .disabled(!model.canSubmitCode)

            Button("Вернуться ко входу") { model.backToCredentials() }
                .foregroundStyle(.secondary)
        } footer: {
            if let error = model.errorMessage {
                Label(error, systemImage: "exclamationmark.triangle")
                    .foregroundStyle(.red)
            }
        }
    }
}
