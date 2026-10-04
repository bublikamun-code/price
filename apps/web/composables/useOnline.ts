// Состояние сети для UI. Приложение — B2B-каталог, и почти каждое действие
// (корзина, заявка, загрузка прайса) идёт на сервер: без индикации пользователь
// нажимает кнопку и получает «тишину» вместо результата.
//
// Экспорт `isOnline` — общий reactive-сингл на модуль, чтобы все баннеры в
// приложении (а их несколько: layout'ы) реагировали на одно событие, а не
// навешивали по своему слушателю.

const online = ref(true)
/** Реально ли мы узнавали офлайн прямо сейчас (на сервере — всегда true). */
const offline = ref(false)
let bound = false

function bind() {
  if (bound || import.meta.server) return
  bound = true

  online.value = navigator.onLine
  window.addEventListener('online', () => {
    online.value = true
  })
  window.addEventListener('offline', () => {
    online.value = false
    // Показываем баннер только после реального обрыва, а не на первой загрузке
    // страницы у пользователя без сети — иначе он увидит предупреждение вместо
    // того, чтобы понять, что приложение надо обновить.
    offline.value = true
  })
}

export function useOnline() {
  if (import.meta.client) {
    onMounted(bind)
    onBeforeUnmount(() => {
      // Слушатели намеренно не снимаем: модульный сингл переживает смену
      // layout'а, а снимать их на каждом размонтировании значило бы навесить
      // заново на каждом переходе и потерять событие между ними.
    })
  }

  return {
    isOnline: readonly(online),
    /** Показывать баннер (только после подтверждённого обрыва связи). */
    showOfflineBanner: readonly(offline),
    dismissOfflineBanner: () => {
      offline.value = false
    },
  }
}