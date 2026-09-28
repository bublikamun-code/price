import Foundation
import shared

/// Экран каталога/прайса: фильтры, сортировка, поиск, догрузка.
///
/// Состояние списка живёт в Kotlin-ядре (`CatalogPager`) — там же, где
/// keyset-пагинация и правило «курсор привязан к фильтрам». Здесь только
/// намерения пользователя и подписка на состояние.
@MainActor
@Observable
final class CatalogViewModel {
    private let pager: CatalogPager
    private let repository: CatalogRepository

    var products: [CatalogProduct] = []
    var isLoading = false
    var isLoadingMore = false
    var hasMore = false
    var isStale = false
    var errorMessage: String?

    var facets = CatalogFacets.empty
    var searchText = ""
    var sort: String = CatalogQuery.Sort.byName
    var priceMode: PriceCalcMode = PriceCalcMode.fixed
    var selectedBrandId: String?
    var selectedSeriesId: String?
    var onlyInStock = false
    var showFilters = false

    // `nonisolated(unsafe)`: `deinit` у Swift не изолирован главным актором,
    // а подписку надо отменить именно там. Значение меняется только из
    // @MainActor-методов этого же типа, поэтому гонки нет.
    nonisolated(unsafe) private var subscription: PagerSubscription?
    private var searchDebounce: Task<Void, Never>?

    init(repository: CatalogRepository) {
        self.repository = repository
        // Диспетчер обязателен: Kotlin не экспортирует значения по умолчанию
        // в Objective-C, поэтому из Swift все четыре аргумента нужны явно.
        // Главный поток — единственный, на котором SwiftUI вправе менять
        // состояние.
        pager = CatalogPager(
            repository: repository,
            initialQuery: CatalogQuery(
                q: nil,
                brandIds: [],
                seriesIds: [],
                stock: nil,
                model: nil,
                sort: CatalogQuery.Sort.byName,
                limit: 50
            ),
            initialPriceMode: .fixed,
            uiDispatcher: PlatformHttpClientKt.mainUiDispatcher()
        )
    }

    deinit {
        subscription?.cancel()
    }

    /// Собирает `CatalogQuery` из того, что набрал пользователь.
    ///
    /// `require(limit in 1..100)` в Kotlin-ядре бросит исключение, если сюда
    /// просочится что-то другое, поэтому `limit` здесь — константа 50,
    /// совпадающая с дефолтом ядра и половиной потолка эндпоинта.
    private var currentQuery: CatalogQuery {
        let trimmed = searchText.trimmingCharacters(in: .whitespacesAndNewlines)
        return CatalogQuery(
            q: trimmed.isEmpty ? nil : trimmed,
            brandIds: selectedBrandId.map { [$0] } ?? [],
            seriesIds: selectedSeriesId.map { [$0] } ?? [],
            stock: onlyInStock ? "IN_STOCK" : nil,
            model: nil,
            sort: sort,
            limit: 50
        )
    }

    func start() async {
        guard subscription == nil else { return }
        // Подписка на ядро: единственный источник правды о том, что показано.
        // Колбэк приходит на главный поток, поэтому менять @Observable-поля
        // можно прямо здесь, без прыжка через Task { @MainActor in }.
        subscription = pager.subscribe { [weak self] state in
            self?.apply(state)
        }
        await loadFacets()
        await reload()
    }

    private func apply(_ state: CatalogUiState) {
        products = state.products
        isLoading = state.isLoading
        isLoadingMore = state.isLoadingMore
        hasMore = state.hasMore
        isStale = state.isStale
        errorMessage = state.error
    }

    private func loadFacets() async {
        do {
            let result: CoreResult<CatalogFacets> = try await withKmpValue { completion in
                repository.facets(completionHandler: completion)
            }
            facets = try value(of: result)
        } catch {
            // Фильтры — вспомогательное. Их отсутствие не должно мешать
            // смотреть каталог, поэтому ошибку показываем пустым списком.
            facets = CatalogFacets.empty
        }
    }

    /// Поиск с задержкой: каждая буква не должна быть запросом к бэкенду.
    func searchTextChanged() {
        searchDebounce?.cancel()
        searchDebounce = Task { [weak self] in
            try? await Task.sleep(for: .milliseconds(350))
            guard !Task.isCancelled, let self else { return }
            await self.reload()
        }
    }

    func reload() async {
        // Kotlin-suspend приходит сюда как completionHandler, а не как
        // `async throws`: без моста Swift ждал бы вечно.
        do {
            try await withKmpCompletion { completion in
                pager.reload(
                    query: currentQuery,
                    priceCalcMode: priceMode,
                    completionHandler: completion
                )
            }
        } catch {
            // reload() уже записал текст ошибки в состояние пагинатора;
            // дублировать его здесь нельзя — иначе один и тот же текст
            // показался бы в разных местах экрана.
        }
    }

    func setSort(_ value: String) async {
        sort = value
        await reload()
    }

    func setPriceMode(_ value: PriceCalcMode) async {
        priceMode = value
        await reload()
    }

    func toggleInStock() async {
        onlyInStock.toggle()
        await reload()
    }

    func selectBrand(_ id: String?) async {
        // Серия принадлежит бренду: смена бренда сбрасывает и её, иначе в
        // выдаче окажется пусто из-за несовместимой пары фильтров.
        selectedBrandId = selectedBrandId == id ? nil : id
        selectedSeriesId = nil
        await reload()
    }

    func selectSeries(_ id: String?) async {
        selectedSeriesId = selectedSeriesId == id ? nil : id
        await reload()
    }

    func resetFilters() async {
        selectedBrandId = nil
        selectedSeriesId = nil
        onlyInStock = false
        searchText = ""
        await reload()
    }

    func loadMoreIfNeeded(currentItem product: CatalogProduct) async {
        guard let last = products.last, last.id == product.id, hasMore else { return }
        try? await withKmpCompletion { completion in
            pager.loadMore(completionHandler: completion)
        }
    }

    /// Серии, отфильтрованные по выбранному бренду.
    var visibleSeries: [SeriesRef] {
        guard let brandId = selectedBrandId else { return facets.series }
        return facets.series.filter { $0.brandId == brandId }
    }
}
