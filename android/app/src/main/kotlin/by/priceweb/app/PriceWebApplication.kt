package by.priceweb.app

import android.app.Application
import by.priceweb.app.core.AppContainer
import coil.ImageLoader
import coil.ImageLoaderFactory
import com.priceweb.core.session.PriceWebPlatform
import okhttp3.Interceptor

/**
 * Приложение создаёт контейнер зависимостей один раз.
 *
 * Контейнер нужен до первого экрана, а не когда тот понадобился: хранилище
 * токенов читает application-контекст, и инициализировать его позже означало бы
 * гонку между `onCreate` и первым обращением к сессии.
 */
class PriceWebApplication : Application(), ImageLoaderFactory {
    lateinit var container: AppContainer
        private set

    override fun onCreate() {
        super.onCreate()
        PriceWebPlatform.install(this)
        container = AppContainer(
            baseUrl = BuildConfig.API_BASE_URL,
            appVersion = BuildConfig.VERSION_NAME,
        )
    }

    /**
     * Загрузчик картинок с авторизацией.
     *
     * Реализация `ImageLoaderFactory` вместо отдельного `ImageLoader` в
     * `setContent` — потому что `AsyncImage` берёт загрузчик из контекста
     * (`LocalImageLoader`), и переопределить его нужно один раз на процесс.
     */
    override fun newImageLoader(): ImageLoader = ImageLoader.Builder(this)
        .okhttpClient {
            // Токен не берётся из хранилища и не зашит в код: interceptor
            // спрашивает кэш, который наполняется `validAccessToken()` ядра.
            addInterceptor(
                Interceptor { chain ->
                    val request = chain.request()
                    val token = container.sessionTokenProvider.peek()
                    if (token.isBlank() || request.header(HEADER_AUTHORIZATION) != null) {
                        chain.proceed(request)
                    } else {
                        chain.proceed(
                            request.newBuilder()
                                .header(HEADER_AUTHORIZATION, "Bearer $token")
                                .build(),
                        )
                    }
                },
            )
        }
        .build()

    private companion object {
        const val HEADER_AUTHORIZATION = "Authorization"
    }
}
