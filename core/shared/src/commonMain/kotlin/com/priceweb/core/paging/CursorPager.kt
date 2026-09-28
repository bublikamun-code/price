package com.priceweb.core.paging

import com.priceweb.core.guardQuietly
import com.priceweb.core.model.CatalogQuery
import com.priceweb.core.model.CatalogProduct
import com.priceweb.core.model.PriceCalcMode
import com.priceweb.core.repository.CatalogRepository
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/**
 * Состояние списка каталога для UI.
 *
 * [isStale] означает «данные относятся к прошлым фильтрам, показать их нельзя,
 * но перерисовывать списк дешевле, чем дёргать сеть». Так сделано, чтобы
 * смена фильтра не мигала пустотой на каждом нажатии.
 */
data class CatalogUiState(
    val products: List<CatalogProduct> = emptyList(),
    val isLoading: Boolean = false,
    val isLoadingMore: Boolean = false,
    val hasMore: Boolean = false,
    val nextCursor: String? = null,
    val query: CatalogQuery = CatalogQuery(),
    val priceCalcMode: PriceCalcMode = PriceCalcMode.FIXED,
    val error: String? = null,
    val isStale: Boolean = false,
) {
    val isEmpty: Boolean get() = products.isEmpty() && !isLoading && error == null
}

/**
 * Отменить подписку на состояние пагинатора.
 *
 * Отдельный класс, а не `Job`, потому что `Job` в Objective-C выглядит как
 * `SharedKotlinx_coroutines_coreJob` с тремя методами, из которых Swift
 * использует один, и выглядит это в коде как шум из чужой библиотеки.
 */
class PagerSubscription internal constructor(private val job: Job) {
    fun cancel() {
        job.cancel()
    }
}

/**
 * Keyset-пагинация каталога.
 *
 * Смена фильтра сбрасывает страницу: курсор, выданный для прошлого набора
 * фильтров, бэкенд теперь отвергнет с 422, а не продолжит выдачу, поэтому
 * хранить его после смены фильтра — верный способ показать пустой каталог.
 *
 * [uiDispatcher] — поток, на котором вызывается [subscribe]-колбэк. По
 * умолчанию `Dispatchers.Default`, а не `Main`: главный поток недоступен в
 * commonMain без платформенной зависимости, и мнимое обещание «колбэк придёт
 * на главный» было бы нарушено на JVM-тестах. SwiftUI передаёт `Main` явно.
 * Compose его не передаёт и обходится без [subscribe]: он читает [state]
 * обычным `collectAsState` в `viewModelScope`, который и так главный, так что
 * значение по умолчанию там безопасно.
 */
class CatalogPager(
    private val repository: CatalogRepository,
    initialQuery: CatalogQuery = CatalogQuery(),
    initialPriceMode: PriceCalcMode = PriceCalcMode.FIXED,
    private val uiDispatcher: CoroutineDispatcher = Dispatchers.Default,
) {
    private val loadMutex = Mutex()

    private val _state = MutableStateFlow(
        CatalogUiState(query = initialQuery, priceCalcMode = initialPriceMode),
    )
    val state: StateFlow<CatalogUiState> = _state.asStateFlow()

    private val subscriptionScope = CoroutineScope(SupervisorJob() + uiDispatcher)

    /**
     * Подписка на состояние для UI, не умеющего читать `StateFlow`.
     *
     * Swift видит `StateFlow` как `SharedKotlinx_coroutines_coreStateFlow`, а
     *collect-лямбду на нём — как `collectWithResult`, который не выражается в
     * Swift-коде без Objective-C-моста. Колбэк здесь избавляет от моста: Swift
     * передаёт обычное замыкание и получает обычное значение.
     *
     * Колбэк вызывается сразу с текущим состоянием, а затем на каждое
     * изменение — иначе первый экран остался бы пустым до первого ответа.
     */
    fun subscribe(onEach: (CatalogUiState) -> Unit): PagerSubscription {
        val job = subscriptionScope.launch {
            _state.collect { onEach(it) }
        }
        return PagerSubscription(job)
    }

    /**
     * Первая страница: смена фильтра, сортировки или режима цены.
     *
     * Метод ничего не возвращает и ничего не бросает: результат — [CatalogUiState],
     * куда и успех, и ошибка уже записаны. Это же делает его безопасным для
     * Objective-C-экспорта, где бросок из `suspend`-функции убивает процесс.
     */
    suspend fun reload(
        query: CatalogQuery = _state.value.query,
        priceCalcMode: PriceCalcMode = _state.value.priceCalcMode,
    ) {
        guardQuietly {
            loadMutex.withLock {
                val filtersChanged = query.pageKey != _state.value.query.pageKey ||
                    priceCalcMode != _state.value.priceCalcMode
                _state.value = _state.value.copy(
                    isLoading = true,
                    error = null,
                    query = query,
                    priceCalcMode = priceCalcMode,
                    // Старые строки остаются видимыми, но помечаются несвежими.
                    isStale = filtersChanged,
                )
                // Репозиторий возвращает CoreResult, а не бросает, — обёртка
                // всё равно нужна: отмена задачи экрана дошла бы до Objective-C
                // как abort.
                val result = repository.products(query, priceCalcMode, cursor = null)
                val page = result.value
                _state.value = if (page != null) {
                    _state.value.copy(
                        products = page.products,
                        isLoading = false,
                        hasMore = page.hasMore,
                        nextCursor = page.nextCursor,
                        error = null,
                        isStale = false,
                    )
                } else {
                    _state.value.copy(
                        isLoading = false,
                        products = if (filtersChanged) emptyList() else _state.value.products,
                        hasMore = false,
                        nextCursor = null,
                        error = result.error?.message ?: "Не удалось загрузить каталог",
                        isStale = false,
                    )
                }
            }
        }
        // Страховка от вечного спиннера: если что-то упало выше по стеку, флаг
        // загрузки мог остаться поднятым, и экран вращал бы колесо без причины.
        if (_state.value.isLoading) {
            _state.value = _state.value.copy(
                isLoading = false,
                error = _state.value.error ?: "Не удалось загрузить каталог",
            )
        }
    }

    /**
     * Следующая страница.
     *
     * Повторный вызов во время загрузки и при отсутствии курсора — no-op:
     * экран догружает скроллом, и повторный вход случается постоянно.
     */
    suspend fun loadMore() {
        val current = _state.value
        if (current.isLoadingMore || current.isLoading || current.isStale) return
        val cursor = current.nextCursor ?: return

        guardQuietly {
            loadMutex.withLock {
                if (_state.value.nextCursor != cursor) return@withLock
                _state.value = _state.value.copy(isLoadingMore = true)
                val result = repository.products(
                    current.query,
                    current.priceCalcMode,
                    cursor = cursor,
                )
                val page = result.value
                _state.value = if (page != null) {
                    _state.value.copy(
                        products = _state.value.products + page.products,
                        isLoadingMore = false,
                        hasMore = page.hasMore,
                        nextCursor = page.nextCursor,
                        error = null,
                    )
                } else {
                    _state.value.copy(
                        isLoadingMore = false,
                        // Курсор оставляем: следующий скролл попробует тот же,
                        // и при кратковременной потере сети это сработает.
                        error = result.error?.message ?: "Не удалось загрузить следующую страницу",
                    )
                }
            }
        }
    }
}
