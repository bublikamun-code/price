# core/ — общее ядро нативных клиентов

Kotlin Multiplatform-ядро для iOS (SwiftUI) и Android (Compose). Здесь только
DTO, HTTP, пагинация и репозитории — **ни UI, ни платформенных API**, кроме
`expect`/`actual` для хранилища токенов.

Канон: `ARCHITECTURE_PLAN.md` §16 п.36 (нативные клиенты), п.37 (v2 media),
контракт — `docs/NATIVE_API_CONTRACT.md`.

## Структура

| Что | Где |
|---|---|
| DTO | `shared/src/commonMain/kotlin/com/priceweb/core/model/` |
| HTTP-клиент, refresh, ошибки | `shared/src/commonMain/.../core/ApiClient.kt`, `ApiException.kt` |
| Репозитории | `shared/src/commonMain/.../core/repository/` |
| Keyset-пагинация | `shared/src/commonMain/.../core/paging/CursorPager.kt` |
| Хранилище токенов | `TokenStore.kt` (`expect`) + `*.jvm.kt`, `*.ios.kt`, `*.android.kt` (`actual`) |
| Тесты на фикстурах | `shared/src/jvmTest/.../ContractFixtureTest.kt` |

## Что можно собрать на этой машине, а что — нет

Нативные таргеты включаются флагами, потому что требуют разного тулчейна:

```bash
# Только JVM: собирает и проверяет всё общее ядро. Нужны лишь JDK 21.
./gradlew :shared:jvmTest

# + iOS: нужен установленный Xcode (Kotlin/Native берёт Apple SDK оттуда).
./gradlew -PenableIos=true :shared:iosSimulatorArm64Test

# + Android: нужен Android SDK (ANDROID_HOME или local.properties).
./gradlew -PenableAndroid=true :shared:androidDebugUnitTest
```

Без флагов собирается `jvm` и прогоняются общие тесты. Это не упрощение
«на потом», а сознательный выбор: общий код от платформы не зависит, а
`TokenStore` для JVM — заглушка ради прогонов, в мобильные сборки она не
попадает.

## Контракт проверяется фикстурами, а не кодогенерацией

Кодогенератора в проекте нет. Единственный способ убедиться, что клиент и
сервер говорят на одном языке, — читать **те же** JSON, что валидирует
пидantic-ом `apps/api/tests/test_contract_artifacts.py`:

```
apps/api/tests/fixtures/v2/*.json  →  core/shared/src/jvmTest/.../ContractFixtureTest.kt
```

Поменяет бэкенд DTO — упадёт тест здесь, а не на устройстве у пользователя.
Если добавите в фикстуры новый файл, не забудьте внести его в
`test_contract_artifacts.py`: иначе он не будет проверяться на стороне сервера.

## Три инварианта, ради которых существует `ApiClient`

1. **Refresh в одном полёте.** Пять экранов, одновременно получившие 401,
   порождают ровно один refresh. Иначе бэкенд увидит повторное использование
   уже отозванного refresh-токена и завершит сессию как подозрительную (§16 п.15).
2. **Один ретрай, и только после refresh.** Повторять запрос со старым
   access-токеном бессмысленно; повторить дважды — цикл.
3. **Отозванные токены стираются.** Refresh, отвергнутый с 401, обязан привести
   к чистому состоянию, иначе приложение бесконечно повторяет один и тот же отказ.

Все три закрыты тестами в `ApiClientTest.kt`.
