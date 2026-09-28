package by.priceweb.app.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.AssistChip
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import by.priceweb.app.core.CatalogViewModel
import com.priceweb.core.model.CatalogQuery

/** Сколько строк недогруженного остатка считается «уже пора грузить дальше». */
const val PREFETCH_ROWS = 3

/** Сортировки в том виде, в каком их ждёт параметр `sort`. */
internal val SORT_OPTIONS = listOf(
    CatalogQuery.SORT_NAME to "По названию",
    CatalogQuery.SORT_NAME_DESC to "По названию ↓",
    CatalogQuery.SORT_PRICE to "Сначала дешёвые",
    CatalogQuery.SORT_PRICE_DESC to "Сначала дорогие",
    CatalogQuery.SORT_SKU to "По артикулу",
)

internal data class ActiveChip(
    val title: String,
    val onClear: () -> Unit,
)

/** Бейджи активных фильтров над списком: показывают, что именно сужает выдачу. */
@Composable
internal fun activeChips(
    state: CatalogViewModel.UiState,
    viewModel: CatalogViewModel,
): List<ActiveChip> = buildList {
    state.brandName(state.brandId)?.let { brand ->
        add(ActiveChip(brand) { viewModel.selectBrand(state.brandId) })
    }
    state.seriesName(state.seriesId)?.let { series ->
        add(ActiveChip(series) { viewModel.selectSeries(state.seriesId) })
    }
    if (state.onlyInStock) {
        add(ActiveChip("Только в наличии") { viewModel.toggleInStock() })
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun FiltersSheet(
    state: CatalogViewModel.UiState,
    viewModel: CatalogViewModel,
    onClose: () -> Unit,
) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)

    ModalBottomSheet(onDismissRequest = onClose, sheetState = sheetState) {
        Column(Modifier.fillMaxWidth().padding(bottom = 24.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth().padding(horizontal = 20.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text("Фильтры", style = MaterialTheme.typography.titleLarge)
                TextButton(onClick = { viewModel.resetFilters() }) { Text("Сбросить") }
            }

            FilterSection(
                title = "Бренд",
                options = state.facets.brands.map { it.id to it.name },
                selectedId = state.brandId,
            ) { id -> viewModel.selectBrand(id) }

            if (state.brandId != null) {
                FilterSection(
                    title = "Серия",
                    options = state.visibleSeries.map { it.id to it.name },
                    selectedId = state.seriesId,
                ) { id -> viewModel.selectSeries(id) }
            }

            Row(
                modifier = Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 12.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text("Только в наличии")
                Switch(
                    checked = state.onlyInStock,
                    onCheckedChange = { viewModel.toggleInStock() },
                )
            }
        }
    }
}

/**
 * Секция фильтра со списком вариантов.
 *
 * Варианты скроллятся: брендов в прайсе бывает больше, чем помещается на
 * экран, и без прокрутки нижние были бы недостижимы на телефоне.
 */
@Composable
private fun FilterSection(
    title: String,
    options: List<Pair<String, String>>,
    selectedId: String?,
    onSelect: (String) -> Unit,
) {
    Column {
        Text(
            title,
            style = MaterialTheme.typography.titleSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(horizontal = 20.dp, vertical = 8.dp),
        )
        if (options.isEmpty()) {
            Text(
                "—",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(horizontal = 20.dp),
            )
        } else {
            LazyColumn(Modifier.fillMaxWidth()) {
                items(options, key = { it.first }) { (id, name) ->
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable { onSelect(id) }
                            .padding(horizontal = 20.dp, vertical = 14.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.SpaceBetween,
                    ) {
                        Text(name, style = MaterialTheme.typography.bodyLarge)
                        if (id == selectedId) {
                            Icon(Icons.Filled.Check, contentDescription = "Выбрано")
                        }
                    }
                    HorizontalDivider()
                }
            }
        }
    }
}
