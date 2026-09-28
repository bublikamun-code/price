# PriceWebApp — iOS-клиент

SwiftUI-приложение поверх общего Kotlin-ядра (`core/`, Kotlin Multiplatform).
Тот же контракт `/api/v2`, тот же клиент сессии, та же пагинация — отличается
только UI-слой.

> **Статус: собирается и запускается на симуляторе arm64.**
> `xcodebuild` → `** BUILD SUCCEEDED **`, приложение установлено и живёт
> (`launchctl` держит процесс, новых crash-репортов нет). Два краша были
> найдены и починены — см. «Две ошибки, которые стоили дороже всего» ниже,
> повторять их не надо.

## Что внутри

| Файл | Назначение |
|---|---|
| `PriceWebApp.swift` | `@main`, гейт авторизации, меню профиля |
| `Core/AppEnvironment.swift` | Точка сборки зависимостей, базовый URL, Ktor `Darwin` |
| `Core/SessionGate.swift` | Восстановление сессии из Keychain при запуске |
| `Core/KmpInterop.swift` | Мост KMP `suspend` → Swift `async`, разбор `CoreResult` |
| `Core/Format.swift` | `Decimal`-разбор денег, «ваша цена», остаток |
| `Core/MediaImage.swift` | Фото по `mediaId` (не по presigned-URL) |
| `Features/Auth/` | Вход и 2FA-челлендж |
| `Features/Catalog/` | Каталог с фильтрами и карточка товара |

## Правило границы: `suspend` наружу не бросает

**Главное правило этого клиента. Нарушение = `Abort trap: 6` на экране.**

Kotlin/Native экспортирует `suspend fun` в Objective-C как метод с
completion-блоком и `NSError *`, но **без атрибута `@Throws`**. Swift не
считает параметр `NSError *` в completion-блоке признаком `throws` и не
ставит `try`, а Kotlin-исключение, дошедшее до этой границы, превращается в
`Kotlin_ObjCExport_runCompletionFailure` → `terminateWithUnhandledException` →
`abort()`. Исключение не летит в Swift, где его можно показать: оно убивает
процесс, и ни один `do/catch` на стороне SwiftUI этого не поймает.

Отсюда правило: **любая `suspend`-функция, которую видят SwiftUI, обязана
возвращать `CoreResult<T>` и не бросать.** Заворачивание живёт в ядре, в
`com.priceweb.core.guarded` (`core/shared/src/commonMain/kotlin/com/priceweb/core/CoreResult.kt`),
а Swift получает значение через `value(of:)` из `Core/KmpInterop.swift`,
которая превращает `CoreError` в `CoreFailure: LocalizedError` — вот его уже
`try` ловит штатно.

Отдельно про отмену: Ktor на Darwin сообщает о сетевом сбое, **закрывая канал
запроса `CancellationException`**. Поэтому `guarded` ловит `CancellationException`
и вызывает `currentCoroutineContext().ensureActive()` — так настоящая отмена
корутины (сворачивание экрана, выход из приложения) отличается от упавшей сети,
а не маскируется под неё.

Побочное следствие: `TokenStore`, `ApiClient` и прочие внутренности ядра из
SwiftUI вызывать нельзя — там `suspend` ещё бросает. Нативный слой получает
токены только через `ApiClient.validAccessToken()` / `currentTokens()`, которые
тоже не бросают.

## Две ошибки, которые стоили дороже всего

### 1. Keychain: C-строки — не CF-объекты

`EXC_BAD_ACCESS` в `der_sizeof_plist` при первом же обращении к Keychain.

Запрос к `SecItem*` строился из Kotlin-строк, попавших в словарь как
`CPointer<__CFString>`. Для моста CoreFoundation этого достаточно — но
`kSecClass`, `kSecAttrService` и прочие ключи обязаны быть **настоящими
`CFStringRef` из `platform.Security`**. Из C-строки Security читал мусор вместо
`isa` и падал, разбирая словарь как property list.

Правильно: ключи и константы — только из `platform.Security`; строку, созданную
через `CFStringCreateWithCString`, надо **держать живой до возврата из вызова
Security** (Kotlin/Native не ARC — отпустится раньше, если не сохранить в
`MemScope`, который живёт дольше вызова).

### 2. Исключение, перелетевшее ObjC-границу

См. «Правило границы» выше. Диагностика, если повторится:

```bash
touch /tmp/crash-marker
# …собрать, поставить, запустить…
find ~/Library/Logs/DiagnosticReports -name 'PriceWebApp*' -newer /tmp/crash-marker
```

Текст Kotlin-исключения на старте виден так:

```bash
xcrun simctl launch --console-pty booted by.priceweb.app
```

Сигнатуры экспорта — не угадывать, а читать в
`core/shared/build/bin/iosSimulatorArm64/debugFramework/shared.framework/Headers/shared.h`.


## Шаги сборки

Нужны Xcode (с iOS 17+ runtime) и JDK 21 — оба ставятся вручную, Xcode через
App Store и Apple ID.

```bash
# 1. Собрать общее ядро под симулятор. Без этого шага Xcode не найдёт `shared`.
cd ../core
JAVA_HOME="$(brew --prefix openjdk@21)" \
  ./gradlew -PenableIos=true :shared:linkDebugFrameworkIosSimulatorArm64
cd ../ios

# 2. Сгенерировать проект из декларации (сам .xcodeproj в репозитории нет).
xcodegen generate

# 3. Собрать и поставить на симулятор (идентификатор устройства — свой).
xcodebuild -project PriceWebApp.xcodeproj -scheme PriceWebApp \
  -configuration Debug -derivedDataPath build \
  -destination 'platform=iOS Simulator,id=<UDID>' build
xcrun simctl install booted build/Build/Products/Debug-iphonesimulator/PriceWebApp.app
xcrun simctl launch booted by.priceweb.app
```

Открыть и собрать вручную — `open PriceWebApp.xcodeproj`.

### Запуск на настоящем iPhone

Симулятор на машине поднят, но окна у него нет (см. «Чего ещё нет»), поэтому
на телефере приложение запускается так:

```bash
# 1. Ядро под устройство — это ДРУГОЙ срез, не переиспользование симуляторного.
cd ../core
JAVA_HOME="$(brew --prefix openjdk@21)" ./gradlew -PenableIos=true :shared:linkDebugFrameworkIosArm64
cd ../ios

# 2. Подставить свою команду подписи (берётся из Xcode → Settings → Accounts).
xcodebuild -project PriceWebApp.xcodeproj -scheme PriceWebApp \
  -configuration Debug -derivedDataPath build-device \
  -destination 'platform=iOS,name=<имя вашего iPhone>' \
  DEVELOPMENT_TEAM=<ABCDE12345> build

xcrun devicectl device install app \
  build-device/Build/Products/Debug-iphoneos/PriceWebApp.app
xcrun devicectl device process launch \
  --console-pty <UDID> by.priceweb.app
```

Три вещи, на которых спотыкается сборка под устройство:

- **Срез фреймворка другой.** Gradle собирает KMP-ядро по одному таргету за
  раз, и `iosArm64` не заменяет `iosSimulatorArm64`. Поэтому в `project.yml`
  пути поиска условны по SDK (`FRAMEWORK_SEARCH_PATHS[sdk=iphoneos*]`) —
  общий список означал бы, что линковщик берёт первый путь и подставляет
  simulator-срез: `ld: building for 'iOS', but linking in object file ... built
  for 'iOS-simulator'`. Та же история с `EXCLUDED_ARCHS`, он нужен только
  симулятору.
- **Подпись.** `DEVELOPMENT_TEAM` в проекте не зашит: это ваш Apple ID, и в
  репозитории ему не место. Без команды сборка идёт, только если
  `CODE_SIGNING_ALLOWED=NO`, — но такой бинарь на телефон не поставится.
- **Адрес API.** `localhost` на телефоне — это сам телефон, поэтому в схеме
  нужен адрес Mac в локальной сети: `PRICEWEB_API_BASE_URL=http://<ip-мака>:8000`.
  Это http, а ATS такие адреса не прикрывает, поэтому в `Info.plist` есть
  `NSAllowsArbitraryLoads`, подставляемый из настройки сборки: `YES` в Debug,
  `NO` в Release. Прод-адрес по https в этом не нуждается.

### Почему симулятору исключён `x86_64`

Gradle собирает KMP-фреймворк по одному таргету за раз, и под симулятор на
Apple Silicon это `iosSimulatorArm64`. `xcodebuild` с generic-дестинацией
(`-destination 'generic/platform=iOS Simulator'`) считает активной
архитектурой обе и линкует `x86_64`, которого во фреймворке нет:

```
Undefined symbols for architecture x86_64:
  "_OBJC_CLASS_$_SharedApiClient", referenced from: in AppEnvironment.o
```

`ONLY_ACTIVE_ARCH: YES` от этого не спасает — при generic-дестинации активная
архитектура не определима, и Xcode всё равно строит обе. Поэтому `x86_64`
исключён для симуляторного SDK явно. На Intel-Mac это уберёт поддержку
симулятора; лечится сборкой XCFramework
(`:shared:assembleIosSimulatorReleaseXCFramework`), которая в проекте пока не
настроена.

## Адрес бэкенда

Берётся из переменной окружения `PRICEWEB_API_BASE_URL`:

- заданная — используется как есть;
- не задана в `DEBUG` — `http://localhost:8000`, то есть uvicorn напрямую;
- не задана в `RELEASE` — падение при старте, а не молчаливая отправка
  персональных цен на `localhost`.

Порт выбран не случайно: `infra/docker-compose.yml` жёстко публикует API на
`8000`, а nginx на этой машине занят соседним проектом и поднят на
`DEV_NGINX_PORT=8081` — идти к нему значит ходить через лишний прокси, где
`/api/v2/media` отдаёт редирект.

Прод-адрес задаётся схемой в Xcode (`Product > Scheme > Run > Arguments >
Environment Variables`) или CI. В репозитории его нет намеренно: это
конфигурация окружения, а не код.

Симулятор ходит на `localhost:8000` напрямую; для проверки на физическом
теле нужен адрес Mac в локальной сети (`make up` поднимает API на
`0.0.0.0`).

## Первый вход

Используйте тестовый аккаунт. Реальные клиентские аккаунты для ручных проверок
не трогать.

## Чего ещё нет

Честный список того, что не проверено:

- **Сцена «войти → каталог» не пройдена глазами.** Приложение запускается и
  живёт, но на этой машине нет окна симулятора: приложение `Simulator.app` в
  установленном Xcode отсутствует (каталога `Developer/Applications` нет,
  `mdfind` не находит его нигде), поэтому `open -a Simulator` даёт «Unable to
  find application named 'Simulator'», а симулятор поднят через `simctl`
  вслепую. Экран видно только снимком экрана (`xcrun simctl io booted
  screenshot`) — он рисуется, но кликнуть по нему нельзя. Так что вход,
  отрисовка прайса и карточка товара живут в коде и компилируются, но
  **руками по экрану ещё не щёлкали**.
- **Сборка под устройство доведена до «линкуется без подписи»
  (`BUILD SUCCEEDED` на `generic/platform=iOS`), но на реальном iPhone не
  запускалась** — нечем: нет Apple ID в Xcode и, соответственно, ни одной
  код-сайнинг идентичности и ни одного provisioning-профиля
  (`security find-identity -p codesigning` → 0). Всё остальное под устройство
  уже настроено и проверено.
- **Данных для показа нет.** На локальном стенде `organization_memberships`
  пуста, поэтому ни один клиент не видит каталог с ценами. Бэкенд при этом
  проверен отдельно: `POST /api/v2/auth/sessions` с `clientType: NATIVE`
  возвращает 200 с `accessToken`/`refreshToken`.
- **Android не собран вовсе** — нет Android SDK. Код `android/` выверен по
  сигнатурам ядра вручную, но ни разу не прошёл компиляцию.
- **Ветка 2FA не проверялась на живом аккаунте** — у тестовых аккаунтов TOTP
  выключен, а включать его ради проверки нельзя без отдельной договорённости.
- **Знак `DEVELOPMENT_TEAM` не проставлен** намеренно: это ваш Apple ID, и в
  репозитории ему не место. На симуляторе подпись не нужна.
