import Foundation
import shared

/// Мост от KMP `suspend`-функций к Swift `async`.
///
/// Kotlin-экспорт отдаёт `suspend fun` в Objective-C как метод с
/// `completionHandler`, а не как `async throws`. Оборачивать каждую точку
/// вызова вручную нельзя — их десятки, и одна забытая обёртка даст «зависший»
/// экран без ошибки. Здесь единственная точка, где живёт континуация.
func withKmpResult<T>(
    _ body: (@escaping (Result<T, Error>) -> Void) -> Void
) async throws -> T {
    try await withCheckedThrowingContinuation { continuation in
        body { result in
            continuation.resume(with: result)
        }
    }
}

/// Мост для Kotlin-методов, чей `completionHandler` отдаёт **два** аргумента:
/// `(значение, ошибка)`. Такой вид даёт Objective-C-экспорт `suspend fun`,
/// если в сигнатуре есть nullable-результат: одним `Result` его не описать.
func withKmpValue<T>(
    _ body: (@escaping (T?, Error?) -> Void) -> Void
) async throws -> T {
    try await withCheckedThrowingContinuation { continuation in
        body { value, error in
            if let error {
                continuation.resume(throwing: error)
            } else if let value {
                continuation.resume(returning: value)
            } else {
                continuation.resume(throwing: KmpMissingValueError())
            }
        }
    }
}

/// Ни значения, ни ошибки от ядра не пришло.
///
/// Отдельный тип нужен, чтобы `userFacingMessage` не выдумывал текст: такое
/// означает баг в ядре, и молча показать «попробуйте ещё раз» значило бы
/// скрыть его от пользователя и от разработчика.
struct KmpMissingValueError: LocalizedError {
    var errorDescription: String? {
        "Ядро вернуло пустой ответ без ошибки."
    }
}

/// Мост для Kotlin-методов без результата: `completionHandler` получает одну
/// ошибку или `nil` при успехе. `pager.reload` и `pager.loadMore` устроены
/// именно так — они меняют состояние пагинатора, а не возвращают значение.
func withKmpCompletion(
    _ body: (@escaping (Error?) -> Void) -> Void
) async throws {
    // Тип континуации указан явно: с пустым `resume()` Swift не может вывести
    // generic-параметр и падает с «failed to produce diagnostic».
    try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
        body { error in
            if let error {
                continuation.resume(throwing: error)
            } else {
                continuation.resume(returning: ())
            }
        }
    }
}

/// Текст ошибки для показа пользователю.
///
/// Kotlin-ядро больше не бросает наружу: `suspend`-функции отдают
/// `CoreResult`, и настоящий текст ошибки лежит в нём самом. Ветки ниже
/// оставлены для тех мест, где ошибка всё же может прийти из Objective-C
/// (мост сам, платформенные API), — выдумывать текст там нельзя.
func userFacingMessage(_ error: Error) -> String {
    let nsError = error as NSError
    if let apiError = try? decodeApiError(nsError) {
        return apiError
    }
    if nsError.domain == "KotlinException", let text = nsError.userInfo["message"] as? String {
        return text
    }
    if nsError.code == 401 {
        return "Сессия истекла. Войдите заново."
    }
    return nsError.localizedDescription
}

/// Ошибка, которую сообщило ядро в [CoreError].
struct CoreFailure: LocalizedError {
    let code: String
    let status: Int32

    var errorDescription: String? { message }
    var message: String

    var isAuthFailure: Bool {
        status == 401 || code == "AUTHENTICATION_REQUIRED" || code == "TOKEN_EXPIRED"
    }

    var isNetworkFailure: Bool { code == "NETWORK_UNAVAILABLE" }
}

/// Разворачивает `CoreResult` в значение или в обычную ошибку Swift.
///
/// `try` здесь — не украшение: Swift позволяет пропустить `try` через
/// `withKmpValue`, а тогда опечатка в поле молча превратилась бы в пустой
/// экран. Приведение типов в сигнатуре делает ошибку видимой компилятору.
func value<T>(of result: CoreResult<T>) throws -> T {
    if let error = result.error {
        throw CoreFailure(
            code: error.code,
            status: error.status,
            message: error.message
        )
    }
    guard let value = result.value else {
        throw KmpMissingValueError()
    }
    return value
}

/// Достаёт `detail` из problem+json, который Kotlin завернул в NSError.
private func decodeApiError(_ error: NSError) -> String? {
    guard let text = error.userInfo["message"] as? String else { return nil }
    guard let start = text.firstIndex(of: "{") else { return nil }
    guard let data = String(text[start...]).data(using: .utf8),
          let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
    else { return nil }
    return object["detail"] as? String
}
