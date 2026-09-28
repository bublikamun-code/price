package by.priceweb.app.core

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.priceweb.core.model.CatalogProduct
import com.priceweb.core.model.PriceCalcMode
import com.priceweb.core.repository.CatalogRepository
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/** Карточка товара: галерея, цены, наличие, характеристики. */
class ProductDetailViewModel(
    private val repository: CatalogRepository,
    private val productId: String,
) : ViewModel() {

    data class UiState(
        val product: CatalogProduct? = null,
        val priceMode: PriceCalcMode = PriceCalcMode.FIXED,
        val isLoading: Boolean = true,
        val error: String? = null,
    )

    private val _state = MutableStateFlow(UiState())
    val state: StateFlow<UiState> = _state.asStateFlow()

    init {
        load()
    }

    fun setPriceMode(value: PriceCalcMode) {
        if (value == _state.value.priceMode) return
        _state.value = _state.value.copy(priceMode = value)
        load()
    }

    fun retry() = load()

    private fun load() {
        val mode = _state.value.priceMode
        _state.value = _state.value.copy(isLoading = true)
        viewModelScope.launch {
            val result = repository.product(productId, mode)
            val product = result.value
            _state.value = _state.value.copy(
                product = product ?: _state.value.product,
                isLoading = false,
                // Повторная загрузка из-за смены режима цены не должна стирать
                // уже показанный товар: ошибка уходит в плашку, карточка — нет.
                error = if (product != null) null else result.error.userMessage(),
            )
        }
    }
}
