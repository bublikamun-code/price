package com.priceweb.core.session

import android.content.Context

/**
 * Точка входа платформенной части: application-контекст Android.
 *
 * Хранилище токенов создаётся в общем коде, где понятия `Context` не
 * существует, и передавать его через `expect`-сигнатуру означало бы тащить
 * `Any?` через весь общий слой. Поэтому Android хранит контекст здесь, а
 * `Application` регистрирует его один раз в `onCreate` — раньше, чем
 * создаётся любой экран.
 */
object PriceWebPlatform {
    private var appContext: Context? = null

    /** Вызывается из `Application.onCreate`. Повторный вызов безвреден. */
    fun install(context: Context) {
        appContext = context.applicationContext
    }

    /**
     * Контекст для хранилища. Бросает исключение с понятным текстом, если
     * приложение забыло вызвать [install]: падать здесь лучше, чем хранить
     * refresh-токен в незашифрованной памяти процесса.
     */
    internal fun requireContext(): Context = checkNotNull(appContext) {
        "PriceWebPlatform.install(this) не вызван в Application.onCreate — " +
            "хранилище токенов не может работать"
    }
}
