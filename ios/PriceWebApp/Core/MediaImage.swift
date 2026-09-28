import SwiftUI
import UIKit
import shared

/// Изображение каталога.
///
/// Загружается не через `AsyncImage`, а вручную: v2-эндпоинт медиа закрыт
/// авторизацией, а `AsyncImage` не умеет подставлять заголовки — картинки
/// просто приходили бы пустыми с 401.
///
/// Кэш живёт здесь, по `MediaResource.id`, а не по `url`. `id` — это
/// `uuid5` от S3-ключа, он не меняется никогда, тогда как `url` может
/// переехать вместе с версией контракта. Кэш по URL пришлось бы
/// инвалидировать при каждом релизе API.
struct MediaImage: View {
    let resource: MediaResource
    let baseURL: URL
    var contentMode: ContentMode = .fill

    @Environment(\.appEnvironment) private var environment
    @State private var phase: Phase = .loading

    private enum Phase {
        case loading
        case loaded(UIImage)
        case failed
    }

    var body: some View {
        content
            .task(id: resource.id) { await load() }
    }

    @ViewBuilder
    private var content: some View {
        switch phase {
        case .loaded(let image):
            Image(uiImage: image)
                .resizable()
                .aspectRatio(contentMode: contentMode)
        case .loading:
            placeholder
                .overlay { ProgressView().controlSize(.small) }
        case .failed:
            placeholder
        }
    }

    private var placeholder: some View {
        ZStack {
            Color(.secondarySystemBackground)
            Image(systemName: "photo")
                .foregroundStyle(.tertiary)
        }
    }

    @MainActor
    private func load() async {
        guard let url = Self.resolve(resource.url, baseURL: baseURL),
              // Окружение внедряется в `WindowGroup`; без него токен взять
              // неоткуда, и приватный эндпоинт медиа вернёт 401 — честнее
              // показать заглушку, чем картинку в полстроки.
              let environment
        else {
            phase = .failed
            return
        }
        // Токен берём у ядра, а не из Keychain напрямую: `validAccessToken`
        // обновит его, если срок на грани, — иначе картинка пришла бы пустой
        // именно в тот момент, когда сессия вот-вот протухнет. Пустая строка —
        // это «сессии нет», и заголовок тогда не ставим вовсе.
        let token = try? await withKmpValue { completion in
            environment.apiClient.validAccessToken(completionHandler: completion)
        }
        let header = (token?.isEmpty == false) ? token : nil
        if let image = await ImageCache.shared.load(key: resource.id, url: url, token: header) {
            phase = .loaded(image)
        } else {
            phase = .failed
        }
    }

    /// `url` в контракте — путь от корня (`/api/v2/media/{id}`), поэтому
    /// склеиваем строками: `appendingPathComponent` нарезал бы путь по слешам.
    private static func resolve(_ path: String, baseURL: URL) -> URL? {
        if let absolute = URL(string: path), absolute.scheme != nil { return absolute }
        let base = baseURL.absoluteString.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        let tail = path.hasPrefix("/") ? String(path.dropFirst()) : path
        return URL(string: "\(base)/\(tail)")
    }
}

/// Процессный кэш картинок по стабильному `mediaId`.
///
/// Отдельный актор, а не `NSCache` в `@State`: перезагрузка строки списка не
/// должна обнулять уже скачанные байты, а между экранами они должны
/// переиспользоваться. Заодно он гасит дубли: один `mediaId` на плитке и в
/// карточке товара грузится один раз, а не дважды.
actor ImageCache {
    static let shared = ImageCache()

    private var storage: [String: UIImage] = [:]
    private var inFlight: [String: Task<UIImage?, Never>] = [:]

    func load(key: String, url: URL, token: String?) async -> UIImage? {
        if let hit = storage[key] { return hit }
        if let task = inFlight[key] { return await task.value }

        let task = Task<UIImage?, Never> { await Self.fetch(url: url, token: token) }
        inFlight[key] = task
        let image = await task.value
        inFlight[key] = nil
        if let image { storage[key] = image }
        return image
    }

    private static func fetch(url: URL, token: String?) async -> UIImage? {
        var request = URLRequest(url: url)
        if let token, !token.isEmpty {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        guard let (data, response) = try? await URLSession.shared.data(for: request),
              let http = response as? HTTPURLResponse,
              (200..<300).contains(http.statusCode),
              let image = UIImage(data: data)
        else { return nil }
        return image
    }

    /// Сброс при выходе из аккаунта: байты прежнего пользователя не должны
    /// пережить смену сессии.
    func removeAll() {
        storage.removeAll()
        for task in inFlight.values { task.cancel() }
        inFlight.removeAll()
    }
}

/// Плитка каталога: фото или заглушка, когда фото у товара нет.
struct ProductThumbnail: View {
    let product: CatalogProduct
    let baseURL: URL
    var size: CGFloat = 64

    var body: some View {
        Group {
            if let thumbnail = product.thumbnail {
                MediaImage(resource: thumbnail, baseURL: baseURL)
            } else {
                ZStack {
                    Color(.secondarySystemBackground)
                    Text(product.sku.prefix(2))
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.tertiary)
                }
            }
        }
        .frame(width: size, height: size)
        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
    }
}
