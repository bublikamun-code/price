package by.priceweb.app.core

import com.priceweb.core.ApiClient
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlin.concurrent.Volatile

/**
 * Токен для запросов, которые идут мимо Ktor, — прежде всего картинок Coil.
 *
 * `/api/v2/media/{id}` закрыт `get_current_user` на бэкенде
 * (`apps/api/app/api/v2/media.py:41`), поэтому картинка без заголовка
 * `Authorization` получает 401 и Coil рисует пустое место. Заголовок ставит
 * OkHttp-interceptor, а interceptor — не coroutine и не умеет ждать: он берёт
 * значение здесь, одним non-suspend чтением поля.
 *
 * Поэтому значение кэшируется, а обновляет его [refresh] — обычная
 * suspend-функция, которую вызывает UI. Кэш нужен ещё и по существу:
 * `ApiClient.accessToken` отдаёт токен «как есть», без запаса перед сроком, и
 * картинка, запрошенная за секунду до истечения, ушла бы с заведомо мёртвым
 * токеном. [ApiClient.validAccessToken] применяет ту же минутную поправку,
 * что и сам `Authorization` в API-запросах, поэтому поведение совпадает.
 *
 * Пустая строка — это «сессии нет», а не «токен пустой»: подставлять её в
 * заголовок нельзя, и [peek] в этом случае ничего не добавляет.
 */
class SessionTokenProvider(private val api: ApiClient) {

    @Volatile
    private var token: String = ""

    private val mutex = Mutex()

    /** Значение для interceptor'а. Не suspend и не ждёт сети. */
    fun peek(): String = token

    /**
     * Обновить кэш. Само обращение к сети здесь возможно: если access-токен у
     * границы срока, ядро refresh'ит его внутри вызова.
     */
    suspend fun refresh(): String = mutex.withLock {
        api.validAccessToken().also { token = it }
    }

    /**
     * Забыть токен.
     *
     * Вызывается на выходе: оставленный в кэше access-токен означал бы, что
     * следующий запрос картинки уйдёт с учётными данными, которые сервер уже
     * отозвал.
     */
    fun invalidate() {
        token = ""
    }
}
