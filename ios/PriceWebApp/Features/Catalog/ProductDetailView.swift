import SwiftUI
import shared

/// Карточка товара: галерея, цены, наличие, характеристики.
struct ProductDetailView: View {
    let productID: String
    let baseURL: URL

    @Environment(AppEnvironment.self) private var environment

    @State private var product: CatalogProduct?
    @State private var errorMessage: String?
    @State private var isLoading = true
    @State private var priceMode: PriceCalcMode = .fixed

    var body: some View {
        ScrollView {
            if let product {
                content(product)
            } else if isLoading {
                ProgressView().padding(.top, 60)
            } else {
                ContentUnavailableView(
                    "Товар не загрузился",
                    systemImage: "exclamationmark.triangle",
                    description: Text(errorMessage ?? "Попробуйте обновить экран")
                )
            }
        }
        .navigationTitle(product?.sku ?? "")
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Menu {
                    Picker("Курс", selection: $priceMode) {
                        Text("Договор").tag(PriceCalcMode.fixed)
                        Text("НБ РБ (текущий)").tag(PriceCalcMode.nbrbCurrent)
                    }
                    .onChange(of: priceMode) { _, _ in Task { await load() } }
                } label: {
                    Image(systemName: "banknote")
                }
            }
        }
    }

    private func content(_ product: CatalogProduct) -> some View {
        VStack(alignment: .leading, spacing: 20) {
            gallery(product)

            VStack(alignment: .leading, spacing: 6) {
                Text(product.name)
                    .font(.title3.weight(.semibold))
                if let brand = product.brand?.name {
                    Text(brand)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
            }

            prices(product)
            stock(product)

            if !product.attributes.isEmpty {
                attributes(product)
            }
        }
        .padding()
    }

    // MARK: - Галерея

    @ViewBuilder
    private func gallery(_ product: CatalogProduct) -> some View {
        let images: [MediaResource] = product.media.isEmpty
            ? product.thumbnail.map { [$0] } ?? []
            : product.media

        if images.isEmpty {
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .fill(Color(.secondarySystemBackground))
                .aspectRatio(1, contentMode: .fit)
                .overlay {
                    Image(systemName: "photo")
                        .font(.largeTitle)
                        .foregroundStyle(.tertiary)
                }
        } else {
            TabView {
                ForEach(images, id: \.id) { resource in
                    MediaImage(resource: resource, baseURL: baseURL, contentMode: .fit)
                        .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
                }
            }
            .frame(height: 300)
            .tabViewStyle(.page)
        }
    }

    // MARK: - Цены

    private func prices(_ product: CatalogProduct) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Ваша цена")
                .font(.caption)
                .foregroundStyle(.secondary)
            Text(product.displayPrice.displayAmount)
                .font(.largeTitle.weight(.bold))

            if product.hasDiscount {
                HStack(spacing: 8) {
                    Text(product.retailPrice.displayAmount)
                        .strikethrough()
                        .foregroundStyle(.secondary)
                    Text("скидка")
                        .font(.caption)
                        .padding(.horizontal, 8)
                        .padding(.vertical, 3)
                        .background(Color.green.opacity(0.15), in: Capsule())
                        .foregroundStyle(.green)
                }
                .font(.subheadline)
            }

            Divider()
            Text("Базовая цена: \(product.basePrice.displayAmount)")
                .font(.caption)
                .foregroundStyle(.secondary)
            // `Rate` — не `Money`: у него `value` (строка), `scale` (число
            // знаков) и `source`. Показываем ровно столько знаков, сколько
            // объявил бэкенд, иначе «12.5000» превратится в «12,5» и перестанет
            // совпадать с прайсом, по которому клиент сверяет сумму.
            Text("Курс: 1 BYN = \(product.exchangeRate.displayValue) · \(product.exchangeRate.source)")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 14))
    }

    private func stock(_ product: CatalogProduct) -> some View {
        HStack {
            Circle()
                .fill(product.isInStock ? Color.green : Color.orange)
                .frame(width: 8, height: 8)
            Text(product.stockDisplay).font(.subheadline)
        }
    }

    // MARK: - Характеристики

    private func attributes(_ product: CatalogProduct) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Характеристики")
                .font(.headline)

            ForEach(attributeRows(product), id: \.0) { key, value in
                HStack(alignment: .top) {
                    Text(key).foregroundStyle(.secondary)
                    Spacer()
                    Text(value).multilineTextAlignment(.trailing)
                }
                .font(.subheadline)
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 14))
    }

    /// Атрибуты приходят свободной картой и могут быть числами либо строками,
    /// поэтому приводим их к строкам через ядро, а не кастом в Swift.
    private func attributeRows(_ product: CatalogProduct) -> [(String, String)] {
        product.attributes.keys.sorted().compactMap { key in
            if let value = product.stringAttribute(key: key), !value.isEmpty {
                return (humanize(key), value)
            }
            return nil
        }
    }

    private func humanize(_ key: String) -> String {
        key.replacingOccurrences(of: "_", with: " ")
            .replacingOccurrences(of: "-", with: " ")
    }

    // MARK: - Загрузка

    private func load() async {
        isLoading = product == nil
        do {
            let result: CoreResult<CatalogProduct> = try await withKmpValue { completion in
                environment.catalogRepository.product(
                    id: productID,
                    priceCalcMode: priceMode,
                    completionHandler: completion
                )
            }
            product = try value(of: result)
            errorMessage = nil
        } catch {
            errorMessage = userFacingMessage(error)
        }
        isLoading = false
    }
}
