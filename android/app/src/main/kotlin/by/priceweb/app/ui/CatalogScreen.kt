package by.priceweb.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AccountCircle
import androidx.compose.material.icons.filled.ArrowDownward
import androidx.compose.material.icons.filled.ArrowUpward
import androidx.compose.material.icons.filled.FilterList
import androidx.compose.material.icons.filled.Sort
import androidx.compose.material3.AssistChip
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextField
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import by.priceweb.app.core.CatalogViewModel
import by.priceweb.app.core.displayAmount
import by.priceweb.app.core.displayPrice
import by.priceweb.app.core.isInStock
import com.priceweb.core.model.CatalogProduct
import com.priceweb.core.model.PriceCalcMode
import coil.compose.AsyncImage

/**
 * Каталог и прайс: список с персональными ценами, поиск, сортировка,
 * фильтры и догрузка по скроллу.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CatalogScreen(
    viewModel: CatalogViewModel,
    mediaBaseUrl: String,
    onOpenProduct: (String) -> Unit,
    onAccount: () -> Unit,
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    var filtersOpen by remember { mutableStateOf(false) }
    val listState = rememberLazyListState()

    LaunchedEffect(Unit) { viewModel.start() }

    // Догрузка: как только до конца списка осталось несколько строк, просим
    // следующую страницу. Порог срабатывает заранее, чтобы на медленной сети
    // не было заметной паузы в конце выдачи.
    val latestProducts by rememberUpdatedState(state.products)
    LaunchedEffect(listState) {
        snapshotFlow {
            val layout = listState.layoutInfo
            val lastIndex = layout.visibleItemsInfo.lastOrNull()?.index ?: -1
            if (lastIndex >= layout.totalItemsCount - PREFETCH_ROWS) lastIndex else -1
        }.collect { index ->
            latestProducts.getOrNull(index)?.let { viewModel.loadMoreIfNeeded(it) }
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Каталог") },
                actions = {
                    IconButton(onClick = onAccount) {
                        Icon(Icons.Filled.AccountCircle, contentDescription = "Профиль")
                    }
                    SortMenu(selected = state.sort, onSelect = viewModel::setSort)
                    PriceModeMenu(selected = state.priceMode, onSelect = viewModel::setPriceMode)
                    IconButton(onClick = { filtersOpen = true }) {
                        Icon(Icons.Filled.FilterList, contentDescription = "Фильтры")
                    }
                },
            )
        },
    ) { padding ->
        Column(modifier = Modifier.fillMaxSize().padding(padding)) {
            SearchField(state.search, viewModel::onSearch)

            val chips = activeChips(state, viewModel)
            if (chips.isNotEmpty()) {
                Row(
                    modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    chips.forEach { chip ->
                        AssistChip(onClick = chip.onClear, label = { Text(chip.title) })
                    }
                }
            }

            when {
                state.isEmpty -> Box(Modifier.fillMaxSize(), Alignment.Center) {
                    Text("Ничего не найдено", color = MaterialTheme.colorScheme.onSurfaceVariant)
                }

                else -> LazyColumn(state = listState, contentPadding = PaddingValues(12.dp)) {
                    if (state.isStale) {
                        item { CenteredProgress() }
                    }
                    items(state.products, key = { it.id }) { product ->
                        ProductRow(
                            product = product,
                            mediaBaseUrl = mediaBaseUrl,
                            onClick = { onOpenProduct(product.id) },
                        )
                        HorizontalDivider()
                    }
                    if (state.isLoadingMore) {
                        item { CenteredProgress() }
                    }
                    state.error?.takeIf { state.products.isNotEmpty() }?.let { message ->
                        item {
                            Text(
                                message,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                style = MaterialTheme.typography.bodySmall,
                                modifier = Modifier.fillMaxWidth().padding(12.dp),
                            )
                        }
                    }
                }
            }
        }
    }

    if (filtersOpen) {
        FiltersSheet(state = state, viewModel = viewModel, onClose = { filtersOpen = false })
    }
}

@Composable
private fun SearchField(value: String, onValueChange: (String) -> Unit) {
    TextField(
        value = value,
        onValueChange = onValueChange,
        placeholder = { Text("Название или артикул") },
        singleLine = true,
        modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp),
    )
}

@Composable
private fun ProductRow(
    product: CatalogProduct,
    mediaBaseUrl: String,
    onClick: () -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth().clickable(onClick = onClick).padding(vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            modifier = Modifier
                .size(56.dp)
                .clip(RoundedCornerShape(10.dp))
                .background(MaterialTheme.colorScheme.surfaceVariant),
            contentAlignment = Alignment.Center,
        ) {
            val thumbnail = product.thumbnail
            if (thumbnail != null) {
                AsyncImage(
                    model = mediaBaseUrl + thumbnail.url,
                    contentDescription = product.name,
                    contentScale = ContentScale.Crop,
                    modifier = Modifier.size(56.dp),
                )
            } else {
                Text(
                    product.sku.take(2),
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }

        Column(
            modifier = Modifier.weight(1f).padding(horizontal = 12.dp),
        ) {
            Text(
                product.name,
                style = MaterialTheme.typography.bodyMedium,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    product.sku,
                    style = MaterialTheme.typography.labelSmall.copy(fontFamily = FontFamily.Monospace),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                if (!product.isInStock) {
                    Text(
                        "  под заказ",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.tertiary,
                    )
                }
            }
        }

        Column(horizontalAlignment = Alignment.End) {
            Text(
                product.displayPrice.displayAmount,
                style = MaterialTheme.typography.bodyMedium,
            )
            if (product.hasDiscount) {
                Text(
                    product.retailPrice.displayAmount,
                    style = MaterialTheme.typography.labelSmall,
                    textDecoration = TextDecoration.LineThrough,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

@Composable
private fun CenteredProgress() {
    Box(Modifier.fillMaxWidth().padding(16.dp), Alignment.Center) {
        CircularProgressIndicator(strokeWidth = 2.dp)
    }
}

@Composable
private fun SortMenu(selected: String, onSelect: (String) -> Unit) {
    var open by remember { mutableStateOf(false) }
    Box {
        IconButton(onClick = { open = true }) {
            Icon(Icons.Filled.Sort, contentDescription = "Сортировка")
        }
        DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
            SORT_OPTIONS.forEach { (value, label) ->
                DropdownMenuItem(
                    text = { Text(label) },
                    onClick = { onSelect(value); open = false },
                    trailingIcon = if (value == selected) {
                        { Icon(Icons.Filled.ArrowDownward, contentDescription = null) }
                    } else {
                        null
                    },
                )
            }
        }
    }
}

@Composable
private fun PriceModeMenu(selected: PriceCalcMode, onSelect: (PriceCalcMode) -> Unit) {
    var open by remember { mutableStateOf(false) }
    Box {
        IconButton(onClick = { open = true }) {
            Icon(Icons.Filled.ArrowUpward, contentDescription = "Курс")
        }
        DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
            DropdownMenuItem(
                text = { Text("Договор") },
                onClick = { onSelect(PriceCalcMode.FIXED); open = false },
            )
            DropdownMenuItem(
                text = { Text("НБ РБ (текущий)") },
                onClick = { onSelect(PriceCalcMode.NBRB_CURRENT); open = false },
            )
        }
    }
}
