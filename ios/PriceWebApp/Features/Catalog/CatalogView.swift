import SwiftUI
import shared

/// Каталог и прайс: список с персональными ценами, поиск, сортировка,
/// фильтры-бейджи и догрузка по скроллу.
struct CatalogView<Accessory: View>: View {
    @Bindable var model: CatalogViewModel
    let baseURL: URL

    /// Кнопки, которые добавляет внешний экран (меню аккаунта).
    ///
    /// Передаются параметром, потому что `NavigationStack` живёт внутри этого
    /// экрана: модификатор `.toolbar`, применённый снаружи, не находит
    /// навигационную панель и молча ничего не рисует.
    @ViewBuilder
    let accessory: () -> Accessory

    init(
        model: CatalogViewModel,
        baseURL: URL,
        @ViewBuilder accessory: @escaping () -> Accessory
    ) {
        self.model = model
        self.baseURL = baseURL
        self.accessory = accessory
    }

    var body: some View {
        NavigationStack {
            List {
                if model.isStale {
                    ProgressView().listRowSeparator(.hidden)
                }

                activeFilters

                if model.products.isEmpty && !model.isLoading {
                    ContentUnavailableView.search(text: model.searchText)
                } else {
                    ForEach(model.products, id: \.id) { product in
                        NavigationLink {
                            ProductDetailView(productID: product.id, baseURL: baseURL)
                        } label: {
                            row(product)
                        }
                        .onAppear { Task { await model.loadMoreIfNeeded(currentItem: product) } }
                    }

                    if model.isLoadingMore {
                        ProgressView().listRowSeparator(.hidden)
                    }
                }

                if let error = model.errorMessage, !model.products.isEmpty {
                    Text(error)
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                        .listRowSeparator(.hidden)
                }
            }
            .listStyle(.plain)
            .navigationTitle("Каталог")
            .searchable(text: $model.searchText, prompt: "Название или артикул")
            .onChange(of: model.searchText) { model.searchTextChanged() }
            .refreshable { await model.reload() }
            .toolbar { toolbar }
            .sheet(isPresented: $model.showFilters) { filters }
            .task { await model.start() }
        }
    }

    // MARK: - Строка

    private func row(_ product: CatalogProduct) -> some View {
        HStack(spacing: 12) {
            ProductThumbnail(product: product, baseURL: baseURL, size: 56)

            VStack(alignment: .leading, spacing: 3) {
                Text(product.name)
                    .font(.subheadline.weight(.medium))
                    .lineLimit(2)

                HStack(spacing: 6) {
                    Text(product.sku)
                        .font(.caption.monospaced())
                        .foregroundStyle(.secondary)
                    if !product.isInStock {
                        Text("под заказ")
                            .font(.caption2)
                            .padding(.horizontal, 6)
                            .padding(.vertical, 2)
                            .background(Color.orange.opacity(0.15), in: Capsule())
                            .foregroundStyle(.orange)
                    }
                }
            }

            Spacer(minLength: 8)

            VStack(alignment: .trailing, spacing: 3) {
                Text(product.displayPrice.displayAmount)
                    .font(.subheadline.weight(.semibold))
                if product.hasDiscount {
                    Text(product.retailPrice.displayAmount)
                        .font(.caption)
                        .strikethrough()
                        .foregroundStyle(.secondary)
                }
            }
        }
        .padding(.vertical, 4)
    }

    // MARK: - Активные фильтры

    @ViewBuilder
    private var activeFilters: some View {
        if !chips.isEmpty {
            Section {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 8) {
                        ForEach(chips, id: \.title) { chip in
                            Button {
                                Task { await chip.clear() }
                            } label: {
                                Label(chip.title, systemImage: "xmark.circle.fill")
                                    .font(.caption)
                                    .padding(.horizontal, 10)
                                    .padding(.vertical, 5)
                                    .background(Color.accentColor.opacity(0.12), in: Capsule())
                            }
                            .buttonStyle(.plain)
                        }
                    }
                    .padding(.vertical, 2)
                }
                .listRowInsets(EdgeInsets(top: 8, leading: 16, bottom: 8, trailing: 0))
                .listRowSeparator(.hidden)
            }
        }
    }

    private struct FilterChip {
        let title: String
        let clear: @MainActor () async -> Void
    }

    private var chips: [FilterChip] {
        var result: [FilterChip] = []
        if let brand = facetsModel.brandName(model.selectedBrandId) {
            result.append(FilterChip(title: brand) { await model.selectBrand(model.selectedBrandId) })
        }
        if let series = facetsModel.seriesName(model.selectedSeriesId) {
            result.append(FilterChip(title: series) { await model.selectSeries(model.selectedSeriesId) })
        }
        if model.onlyInStock {
            result.append(FilterChip(title: "Только в наличии") { await model.toggleInStock() })
        }
        return result
    }

    private var facetsModel: FacetLookup { FacetLookup(facets: model.facets) }

    // MARK: - Панель инструментов

    @ToolbarContentBuilder
    private var toolbar: some ToolbarContent {
        ToolbarItem(placement: .topBarLeading) {
            Menu {
                Picker("Курс", selection: Bindable(model).priceMode) {
                    Text("Договор").tag(PriceCalcMode.fixed)
                    Text("НБ РБ (текущий)").tag(PriceCalcMode.nbrbCurrent)
                }
            } label: {
                Image(systemName: "banknote")
            }
        }

        ToolbarItem(placement: .topBarTrailing) {
            Menu {
                Picker("Сортировка", selection: Bindable(model).sort) {
                    // Значения берутся из ядра: строки обязаны совпадать с
                    // `sort` бэкенда, иначе Fastima вернёт 422.
                    ForEach(CatalogQuery.Sort.all, id: \.value) { option in
                        Text(option.title).tag(option.value)
                    }
                }
            } label: {
                Image(systemName: "arrow.up.arrow.down")
            }
        }

        ToolbarItem(placement: .topBarTrailing) {
            Button { model.showFilters = true } label: {
                Image(systemName: model.showFilters ? "line.3.horizontal.decrease.circle.fill"
                                                  : "line.3.horizontal.decrease.circle")
            }
        }

        ToolbarItem(placement: .topBarTrailing) { accessory() }
    }

    // MARK: - Фильтры

    private var filters: some View {
        NavigationStack {
            Form {
                Section("Бренд") {
                    if model.facets.brands.isEmpty {
                        Text("—").foregroundStyle(.secondary)
                    }
                    ForEach(model.facets.brands, id: \.id) { brand in
                        Button {
                            Task { await model.selectBrand(brand.id) }
                        } label: {
                            HStack {
                                Text(brand.name)
                                Spacer()
                                if model.selectedBrandId == brand.id {
                                    Image(systemName: "checkmark")
                                }
                            }
                        }
                    }
                }

                if model.selectedBrandId != nil {
                    Section("Серия") {
                        if model.visibleSeries.isEmpty {
                            Text("—").foregroundStyle(.secondary)
                        }
                        ForEach(model.visibleSeries, id: \.id) { series in
                            Button {
                                Task { await model.selectSeries(series.id) }
                            } label: {
                                HStack {
                                    Text(series.name)
                                    Spacer()
                                    if model.selectedSeriesId == series.id {
                                        Image(systemName: "checkmark")
                                    }
                                }
                            }
                        }
                    }
                }

                Section("Наличие") {
                    Toggle("Только в наличии", isOn: Bindable(model).onlyInStock)
                }

                Section {
                    Button("Сбросить фильтры") { Task { await model.resetFilters() } }
                }
            }
            .navigationTitle("Фильтры")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Готово") { model.showFilters = false }
                }
            }
        }
        .presentationDetents([.medium, .large])
    }
}

/// Поиск названий бренда и серии по id — для бейджей активных фильтров.
private struct FacetLookup {
    let facets: CatalogFacets
    func brandName(_ id: String?) -> String? {
        guard let id else { return nil }
        return facets.brands.first { $0.id == id }?.name
    }
    func seriesName(_ id: String?) -> String? {
        guard let id else { return nil }
        return facets.series.first { $0.id == id }?.name
    }
}
