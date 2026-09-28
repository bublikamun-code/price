package by.priceweb.app.core

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.priceweb.core.model.CatalogFacets
import com.priceweb.core.model.CatalogProduct
import com.priceweb.core.model.CatalogQuery
import com.priceweb.core.model.PriceCalcMode
import com.priceweb.core.paging.CatalogPager
import com.priceweb.core.repository.CatalogRepository
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * Экран каталога/прайса: фильтры, сортировка, поиск, догрузка.
 *
 * Состояние списка живёт в общем ядре (`CatalogPager`) — там же, где
 * keyset-пагинация и правило «курсор выдан для этих фильтров». Здесь только
 * намерения пользователя.
 */
class CatalogViewModel(private val repository: CatalogRepository) : ViewModel() {

    data class UiState(
        val products: List<CatalogProduct> = emptyList(),
        val facets: CatalogFacets = CatalogFacets(),
        val isLoading: Boolean = false,
        val isLoadingMore: Boolean = false,
        val isStale: Boolean = false,
        val hasMore: Boolean = false,
        val search: String = "",
        val sort: String = CatalogQuery.SORT_NAME,
        val priceMode: PriceCalcMode = PriceCalcMode.FIXED,
        val brandId: String? = null,
        val seriesId: String? = null,
        val onlyInStock: Boolean = false,
        val error: String? = null,
    ) {
        val isEmpty: Boolean get() = products.isEmpty() && !isLoading && error == null

        /** Серии показываем только внутри выбранного бренда. */
        val visibleSeries: List<com.priceweb.core.model.SeriesRef>
            get() = facets.series.filter { brandId == null || it.brandId == brandId }

        fun brandName(id: String?): String? =
            id?.let { wanted -> facets.brands.firstOrNull { it.id == wanted }?.name }

        fun seriesName(id: String?): String? =
            id?.let { wanted -> facets.series.firstOrNull { it.id == wanted }?.name }
    }

    private val pager = CatalogPager(repository)
    private val _state = MutableStateFlow(UiState())
    val state: StateFlow<UiState> = _state.asStateFlow()

    private var observeJob: Job? = null
    private var searchDebounce: Job? = null

    fun start() {
        if (observeJob != null) return
        observeJob = viewModelScope.launch {
            pager.state.collect { core ->
                _state.update {
                    it.copy(
                        products = core.products,
                        isLoading = core.isLoading,
                        isLoadingMore = core.isLoadingMore,
                        isStale = core.isStale,
                        hasMore = core.hasMore,
                        error = core.error,
                        priceMode = core.priceCalcMode,
                    )
                }
            }
        }
        viewModelScope.launch {
            // Фильтры вспомогательные: их отсутствие не должно мешать смотреть
            // каталог, поэтому ошибка здесь не показывается.
            repository.facets().value?.let { facets ->
                _state.update { it.copy(facets = facets) }
            }
        }
        viewModelScope.launch { pager.reload(currentQuery(), _state.value.priceMode) }
    }

    /**
     * Запрос из того, что набрал пользователь.
     *
     * `limit` — константа: ядро требует 1..100 и бросает на другом значении
     * исключение уже в момент создания объекта, то есть на главном потоке.
     */
    private fun currentQuery() = _state.value.let { s ->
        CatalogQuery(
            q = s.search.trim().takeIf { it.isNotEmpty() },
            brandIds = s.brandId?.let { listOf(it) } ?: emptyList(),
            seriesIds = s.seriesId?.let { listOf(it) } ?: emptyList(),
            stock = if (s.onlyInStock) "IN_STOCK" else null,
            model = null,
            sort = s.sort,
            limit = 50,
        )
    }

    fun onSearch(value: String) {
        _state.update { it.copy(search = value) }
        // Каждая буква не должна быть запросом к бэкенду.
        searchDebounce?.cancel()
        searchDebounce = viewModelScope.launch {
            delay(350)
            reload()
        }
    }

    fun setSort(value: String) {
        _state.update { it.copy(sort = value) }
        reload()
    }

    fun setPriceMode(value: PriceCalcMode) {
        _state.update { it.copy(priceMode = value) }
        reload()
    }

    fun toggleInStock() {
        _state.update { it.copy(onlyInStock = !it.onlyInStock) }
        reload()
    }

    fun selectBrand(id: String?) {
        _state.update {
            it.copy(
                brandId = if (it.brandId == id) null else id,
                // Серия принадлежит бренду: оставлять пару «чужой бренд +
                // его серия» значит гарантированно получить пустую выдачу.
                seriesId = null,
            )
        }
        reload()
    }

    fun selectSeries(id: String?) {
        _state.update { it.copy(seriesId = if (it.seriesId == id) null else id) }
        reload()
    }

    fun resetFilters() {
        _state.update {
            it.copy(brandId = null, seriesId = null, onlyInStock = false, search = "")
        }
        searchDebounce?.cancel()
        reload()
    }

    fun reload() {
        viewModelScope.launch { pager.reload(currentQuery(), _state.value.priceMode) }
    }

    fun loadMoreIfNeeded(current: CatalogProduct) {
        val s = _state.value
        if (s.products.lastOrNull()?.id != current.id || !s.hasMore) return
        viewModelScope.launch { pager.loadMore() }
    }
}
