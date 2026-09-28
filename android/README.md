# PriceWebApp — Android-клиент

Compose-приложение поверх общего Kotlin-ядра (`core/shared`, Kotlin
Multiplatform). Тот же контракт `/api/v2`, тот же клиент сессии, та же
keyset-пагинация — отличается только UI-слой. Функционально Android равен
iOS, а не «урезанной копией».

> **Статус: код написан, но не скомпилирован.** На машине, где писался этот
> клиент, не было Android SDK. Первая сборка — у вас, по шагам ниже.

## Что внутри

| Файл | Назначение |
|---|---|
| `PriceWebApplication.kt` | Регистрация контекста и контейнера зависимостей |
| `core/AppContainer.kt` | Ktor `OkHttp`, репозитории, базовый URL |
| `core/AppViewModel.kt` | Гейт авторизации, восстановление сессии |
| `core/LoginViewModel.kt` | Вход и 2FA-челлендж |
| `core/CatalogViewModel.kt` | Фильтры, сортировка, догрузка поверх `CatalogPager` |
| `core/Format.kt` | `BigDecimal`-разбор денег, «ваша цена», остаток |
| `core/SessionTokenProvider.kt` | Кэш access-токена для запросов мимо Ktor (картинки Coil) |
| `ui/` | Тема, вход, каталог с фильтрами, карточка товара |

## Шаги сборки

Нужен JDK 21 и Android SDK (platform 35, build-tools 35).

```bash
# Собрать общее ядро под Android — оно подключается как подпроект,
# отдельный шаг не нужен. Просто:
cd android
./gradlew :app:assembleDebug
```

`./gradlew :shared:jvmTest` в каталоге `core/` проверяет общее ядро без
Android SDK: те же 26 тестов на тех же фикстурах, что и у бэкенда.

Версия Kotlin-плагина в `android/build.gradle.kts` обязана совпадать с
`core/build.gradle.kts`: `:shared` подключён отсюда как подпроект, и две
разные KGP в одной сборке означают, что метаданные ядра не прочитаются.

## Адрес бэкенда

Задаётся при сборке, а не зашивается в код: забытый literal в release
означал бы отправку персональных цен клиента на `localhost`.

```bash
./gradlew :app:assembleRelease -Ppriceweb.apiBaseUrl=https://api.example.com
```

Значение попадает в `BuildConfig.API_BASE_URL`. Если его не задать, debug
соберётся на `http://10.0.2.2:8080` (хост разработчика, видимый из
эмулятора), а release — упадёт при старте с понятным сообщением.

Cleartext-трафик разрешён только для `10.0.2.2` и `localhost`
(`res/xml/network_security_config.xml`): на боевом адресе API работает по
HTTPS, и разрешать cleartext для всего интернета означало бы разрешить
перехват цен по дороге.

## Первый вход

Используйте тестовый аккаунт. Реальные клиентские аккаунты для ручных
проверок не трогать.

## Хранение токенов

`EncryptedSharedPreferences` (реализация `TokenStore` в
`core/shared/src/androidMain`). Refresh-токен живёт семь дней и равен по
силе паролю, поэтому в обычных `SharedPreferences` он не хранится: файл
настроек читается бэкапом и root'ом. Формат хранения совпадает с iOS —
весь grant одной JSON-строкой.
