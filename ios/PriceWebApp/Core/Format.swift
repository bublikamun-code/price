import Foundation
import shared

/// Разбор денежной строки контракта в `Decimal`.
///
/// На проводе `Money.amount` — строка с двумя знаками («294.90»). Для показа
/// нужен `Decimal`: `Double` здесь дал бы «294,90 ₽» вместо «294,90 BYN» и
/// разъезжающиеся копейки в итоговой сумме заказа.
func decimal(from amount: String) -> Decimal? {
    Decimal(string: amount, locale: Locale(identifier: "en_US_POSIX"))
}

extension Money {
    /// «294,90 BYN» — с локальным разделителем, но без изменения величины.
    var displayAmount: String {
        guard let value = decimal(from: amount) else { return amount }
        let formatter = NumberFormatter()
        formatter.numberStyle = .decimal
        formatter.locale = .current
        formatter.minimumFractionDigits = 2
        formatter.maximumFractionDigits = 2
        let text = formatter.string(from: value as NSDecimalNumber) ?? amount
        return "\(text) \(currency)"
    }

    /// Число без валюты — для мест, где валюта подписана один раз сверху.
    var displayNumber: String {
        guard let value = decimal(from: amount) else { return amount }
        let formatter = NumberFormatter()
        formatter.numberStyle = .decimal
        formatter.locale = .current
        formatter.minimumFractionDigits = 2
        formatter.maximumFractionDigits = 2
        return formatter.string(from: value as NSDecimalNumber) ?? amount
    }
}

extension CatalogFacets {
    /// Пустой набор фильтров.
    ///
    /// Kotlin-конструктор без аргументов в Objective-C не экспортируется:
    /// Swift видит только `init(brands:series:stockStatuses:models:)`, хотя в
    /// Kotlin все четыре поля имеют значения по умолчанию. Собирать пустой
    /// набор руками в каждом месте — значит через месяц забыть про одно поле
    /// и получить падение на `fatalError` при добавлении нового.
    static var empty: CatalogFacets {
        CatalogFacets(brands: [], series: [], stockStatuses: [], models: [])
    }
}

extension CatalogQuery {
    /// Сортировки из ядра: строки обязаны совпадать с `sort` на бэкенде.
    enum Sort {
        static var byName: String { CatalogQuery.Companion.shared.SORT_NAME }
        static var byNameDesc: String { CatalogQuery.Companion.shared.SORT_NAME_DESC }
        static var byPrice: String { CatalogQuery.Companion.shared.SORT_PRICE }
        static var byPriceDesc: String { CatalogQuery.Companion.shared.SORT_PRICE_DESC }
        static var bySku: String { CatalogQuery.Companion.shared.SORT_SKU }

        /// Подписи в том порядке, в каком они идут в меню.
        static let all: [(value: String, title: String)] = [
            (byName, "По названию"),
            (byNameDesc, "По названию ↓"),
            (byPrice, "По цене ↑"),
            (byPriceDesc, "По цене ↓"),
            (bySku, "По артикулу")
        ]
    }
}

extension Rate {
    /// Курс с ровно тем числом знаков, которое объявил бэкенд в `scale`.
    ///
    /// На проводе `value` — строка («12.5000»), а `scale` говорит, сколько
    /// знаков после запятой значащих. Доверять одной строке нельзя: она
    /// приходит из Python и может быть «12.5» при `scale = 4`, а клиент,
    /// который умножит на неё сумму, получит копеечную ошибку в каждом заказе.
    var displayValue: String {
        let places = Int(scale)
        let raw = value
        guard places > 0, let parsed = decimal(from: raw) else { return raw }
        let formatter = NumberFormatter()
        formatter.numberStyle = .decimal
        formatter.locale = .current
        formatter.minimumFractionDigits = places
        formatter.maximumFractionDigits = places
        return formatter.string(from: parsed as NSDecimalNumber) ?? raw
    }
}

extension CatalogProduct {
    /// Цена, которую видит клиент: персональная, если она есть.
    var displayPrice: Money { hasDiscount ? clientPrice : retailPrice }

    /// Человекочитаемый остаток: количество бессмысленно, если статус «под заказ».
    ///
    /// `stockQuantity` — `KotlinInt`, а не `Int`: он не отвечает на `>`
    /// сам по себе, поэтому сравниваем через приведение к `Int32`. Приводить
    /// надо явно, а не «на всякий случай обнулять»: отрицательный остаток
    /// бэкенд прислать не может, а вот `null` — обычное дело для товара без
    /// учёта, и путать его с нулём нельзя.
    var stockDisplay: String {
        switch stockStatus {
        case "IN_STOCK":
            guard let quantity = stockQuantity, Int32(quantity) > 0 else { return "В наличии" }
            return "В наличии: \(quantity)"
        case "PREORDER":
            return "Под заказ"
        default:
            return stockStatus
        }
    }

    /// Товар в наличии — от неё зависит, можно ли добавлять в корзину.
    var isInStock: Bool { stockStatus == "IN_STOCK" }
}
