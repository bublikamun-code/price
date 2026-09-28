package by.priceweb.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import by.priceweb.app.core.AppContainer
import by.priceweb.app.core.AppViewModel
import by.priceweb.app.core.CatalogViewModel
import by.priceweb.app.core.LoginViewModel
import by.priceweb.app.core.ProductDetailViewModel
import by.priceweb.app.core.SessionState
import by.priceweb.app.ui.CatalogScreen
import by.priceweb.app.ui.LoginScreen
import by.priceweb.app.ui.PriceWebTheme
import by.priceweb.app.ui.ProductDetailScreen
import kotlinx.coroutines.delay

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)

        val container = (application as PriceWebApplication).container
        setContent {
            PriceWebTheme {
                Surface(modifier = Modifier.fillMaxSize()) {
                    PriceWebApp(container)
                }
            }
        }
    }
}

private object Routes {
    const val CATALOG = "catalog"
    const val PRODUCT = "product/{id}"
    fun product(id: String) = "product/$id"
}

/**
 * Как часто кэш токена для картинок сверяется с ядром.
 *
 * Access живёт 15 минут, и ядро обновляет его само, если до срока меньше
 * минуты. Период нужен только чтобы не ждать ровно момента истечения, а не
 * чтобы дублировать refresh: значение всё равно приходит из
 * `ApiClient.validAccessToken()`.
 */
private const val MEDIA_TOKEN_REFRESH_MS = 5 * 60 * 1000L

/**
 * Корень приложения: гейт авторизации, а внутри — навигация по каталогу.
 *
 * Навигация живёт внутри ветки «залогинен», а не рядом с ней, чтобы выход
 * не оставлял на экране открытой карточку товара, до которой у гостя уже
 * нет доступа.
 */
@Composable
fun PriceWebApp(container: AppContainer) {
    val appViewModel: AppViewModel = viewModel(
        factory = factoryOf { AppViewModel(container.authRepository) },
    )
    val session by appViewModel.session.collectAsStateWithLifecycle()

    LaunchedEffect(Unit) { appViewModel.restore() }

    // Кэш токена для картинок живёт, пока жива сессия. Обновляем его и на
    // входе, и дальше по таймеру: `validAccessToken()` сам разбирается с
    // границей срока, а на выходе кэш стирается — иначе следующая картинка
    // ушла бы с токеном, который сервер уже отозвал.
    LaunchedEffect(session is SessionState.Authenticated) {
        if (session is SessionState.Authenticated) {
            while (true) {
                // `validAccessToken()` не бросает: недоступный сервер — это
                // пустая строка, то есть «картинка без заголовка», а не
                // падение композиции.
                container.sessionTokenProvider.refresh()
                delay(MEDIA_TOKEN_REFRESH_MS)
            }
        } else {
            container.sessionTokenProvider.invalidate()
        }
    }

    when (val current = session) {
        SessionState.Restoring -> Box(Modifier.fillMaxSize(), Alignment.Center) {
            CircularProgressIndicator()
        }

        SessionState.Anonymous -> {
            val loginViewModel: LoginViewModel = viewModel(
                factory = factoryOf { LoginViewModel(container.authRepository) },
            )
            val authenticated by loginViewModel.authenticated.collectAsStateWithLifecycle()
            LaunchedEffect(authenticated) {
                if (authenticated) appViewModel.didAuthenticate()
            }
            LoginScreen(loginViewModel)
        }

        is SessionState.Authenticated -> CatalogNavigation(
            container = container,
            appViewModel = appViewModel,
            account = "${current.user.fullName}\n${current.user.email}",
        )
    }
}

@Composable
private fun CatalogNavigation(
    container: AppContainer,
    appViewModel: AppViewModel,
    account: String,
) {
    val navController = rememberNavController()
    var accountOpen by remember { mutableStateOf(false) }

    NavHost(navController = navController, startDestination = Routes.CATALOG) {
        composable(Routes.CATALOG) {
            val catalogViewModel: CatalogViewModel = viewModel(
                factory = factoryOf { CatalogViewModel(container.catalogRepository) },
            )
            CatalogScreen(
                viewModel = catalogViewModel,
                mediaBaseUrl = container.baseUrl,
                onOpenProduct = { navController.navigate(Routes.product(it)) },
                onAccount = { accountOpen = true },
            )
        }

        composable(Routes.PRODUCT) { entry ->
            val id = entry.arguments?.getString("id").orEmpty()
            val detailViewModel: ProductDetailViewModel = viewModel(
                factory = factoryOf { ProductDetailViewModel(container.catalogRepository, id) },
            )
            ProductDetailScreen(
                viewModel = detailViewModel,
                mediaBaseUrl = container.baseUrl,
                onBack = { navController.popBackStack() },
            )
        }
    }

    if (accountOpen) {
        AlertDialog(
            onDismissRequest = { accountOpen = false },
            title = { Text("Аккаунт") },
            text = { Text(account) },
            confirmButton = {
                TextButton(
                    onClick = {
                        accountOpen = false
                        appViewModel.refresh()
                    },
                ) { Text("Обновить") }
            },
            dismissButton = {
                TextButton(
                    onClick = {
                        accountOpen = false
                        appViewModel.signOut()
                    },
                ) { Text("Выйти") }
            },
        )
    }
}

/**
 * Фабрика для ViewModel с конструкторными аргументами.
 *
 * Прямое создание ViewModel в composable запрещено: она пережила бы
 * рекомпозицию и потеряла состояние при повороте экрана. Фабрика собирает
 * её один раз на узел навигации.
 */
private inline fun <reified T : ViewModel> factoryOf(
    crossinline create: () -> T,
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    @Suppress("UNCHECKED_CAST")
    override fun <VM : ViewModel> create(modelClass: Class<VM>): VM = create() as VM
}
