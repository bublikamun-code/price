package by.priceweb.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import by.priceweb.app.core.ProductDetailViewModel
import by.priceweb.app.core.displayAmount
import by.priceweb.app.core.displayPrice
import by.priceweb.app.core.displayValue
import by.priceweb.app.core.humanize
import by.priceweb.app.core.stockDisplay
import com.priceweb.core.model.CatalogProduct
import com.priceweb.core.model.PriceCalcMode
import coil.compose.AsyncImage

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ProductDetailScreen(
    viewModel: ProductDetailViewModel,
    mediaBaseUrl: String,
    onBack: () -> Unit,
) {
    val state by viewModel.state.collectAsStateWithLifecycle()

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(state.product?.sku ?: "Товар") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Назад")
                    }
                },
                actions = {
                    SingleChoiceSegmentedButtonRow {
                        val modes = PriceCalcMode.entries
                        modes.forEachIndexed { index, mode ->
                            SegmentedButton(
                                selected = state.priceMode == mode,
                                onClick = { viewModel.setPriceMode(mode) },
                                shape = SegmentedButtonDefaults.itemShape(index, modes.size),
                            ) {
                                Text(if (mode == PriceCalcMode.FIXED) "Договор" else "НБ РБ")
                            }
                        }
                    }
                },
            )
        },
    ) { padding ->
        val product = state.product
        when {
            product != null -> ProductContent(product, mediaBaseUrl, Modifier.padding(padding))
            state.isLoading -> Box(Modifier.fillMaxSize().padding(padding), Alignment.Center) {
                CircularProgressIndicator()
            }

            else -> Box(Modifier.fillMaxSize().padding(padding), Alignment.Center) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(
                        state.error ?: "Товар не загрузился",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Text(
                        "Повторить",
                        color = MaterialTheme.colorScheme.primary,
                        modifier = Modifier
                            .padding(top = 12.dp)
                            .tapTarget(viewModel::retry),
                    )
                }
            }
        }
    }
}

@Composable
private fun ProductContent(
    product: CatalogProduct,
    mediaBaseUrl: String,
    modifier: Modifier = Modifier,
) {
    LazyColumn(
        modifier = modifier.fillMaxSize(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        item { Gallery(product, mediaBaseUrl) }

        item {
            Column {
                Text(product.name, style = MaterialTheme.typography.titleMedium)
                product.brand?.name?.let {
                    Text(
                        it,
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }

        item { PriceBlock(product) }

        item {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(
                    Modifier
                        .size(8.dp)
                        .clip(CircleShape)
                        .background(
                            if (product.stockStatus == "IN_STOCK") {
                                MaterialTheme.colorScheme.primary
                            } else {
                                MaterialTheme.colorScheme.tertiary
                            },
                        ),
                )
                Text(
                    product.stockDisplay,
                    style = MaterialTheme.typography.bodyMedium,
                    modifier = Modifier.padding(start = 8.dp),
                )
            }
        }

        val attributes = product.attributes.keys.sorted().mapNotNull { key ->
            product.stringAttribute(key)
                ?.takeIf { it.isNotEmpty() }
                ?.let { key.humanize() to it }
        }
        if (attributes.isNotEmpty()) {
            item {
                Column(
                    Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(14.dp))
                        .background(MaterialTheme.colorScheme.surfaceVariant)
                        .padding(16.dp),
                ) {
                    Text("Характеристики", style = MaterialTheme.typography.titleSmall)
                    attributes.forEach { (key, value) ->
                        Row(
                            Modifier.fillMaxWidth().padding(vertical = 6.dp),
                            horizontalArrangement = Arrangement.SpaceBetween,
                        ) {
                            Text(
                                key,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                style = MaterialTheme.typography.bodyMedium,
                            )
                            Text(value, style = MaterialTheme.typography.bodyMedium)
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun Gallery(product: CatalogProduct, mediaBaseUrl: String) {
    // Галерея приходит из detail-проекции; если её нет, показываем превью
    // из плитки — карточка не должна оставаться пустой из-за отсутствия
    // второго фото у товара.
    val images = product.media.ifEmpty { listOfNotNull(product.thumbnail) }
    if (images.isEmpty()) {
        Box(
            Modifier
                .fillMaxWidth()
                .aspectRatio(1f)
                .clip(RoundedCornerShape(16.dp))
                .background(MaterialTheme.colorScheme.surfaceVariant),
            contentAlignment = Alignment.Center,
        ) {
            Text("Нет фото", color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    } else {
        val pagerState = rememberPagerState(pageCount = { images.size })
        HorizontalPager(state = pagerState) { page ->
            AsyncImage(
                model = mediaBaseUrl + images[page].url,
                contentDescription = product.name,
                contentScale = ContentScale.Crop,
                modifier = Modifier
                    .fillMaxWidth()
                    .aspectRatio(1f)
                    .clip(RoundedCornerShape(16.dp)),
            )
        }
    }
}

@Composable
private fun PriceBlock(product: CatalogProduct) {
    Column(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(14.dp))
            .background(MaterialTheme.colorScheme.surfaceVariant)
            .padding(16.dp),
    ) {
        Text(
            "Ваша цена",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Text(product.displayPrice.displayAmount, style = MaterialTheme.typography.headlineSmall)

        if (product.hasDiscount) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    product.retailPrice.displayAmount,
                    textDecoration = TextDecoration.LineThrough,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodyMedium,
                )
                Text(
                    "  скидка",
                    color = MaterialTheme.colorScheme.primary,
                    style = MaterialTheme.typography.labelSmall,
                )
            }
        }

        HorizontalDivider(Modifier.padding(vertical = 8.dp))
        Text(
            "Базовая цена: ${product.basePrice.displayAmount}",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Text(
            "Курс: 1 BYN = ${product.exchangeRate.displayValue} · ${product.exchangeRate.source}",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}
