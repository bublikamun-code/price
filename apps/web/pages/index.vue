<script setup lang="ts">
// Главная страница: гость видит маркетинговый лендинг (SITEMAP.md §5),
// авторизованный клиент — компактный дашборд (заявки / избранное / файлы).
import type {
  BannerRead,
  FavoriteListPage,
  FileAsset,
  FileAssetPage,
  NewsPage,
  NewsRead,
  OrderListPage,
  OrderRead,
  OrderStatus,
} from '~/types/api'

useHead({ title: 'Главная' })
// OG-мета лендинга (§16 п.29); og:image не задаём — ассета пока нет.
useSeoMeta({
  ogTitle: 'PricePortal — B2B-портал с персональными прайс-листами',
  ogDescription: 'Личный кабинет с динамическими ценами по вашему договору, импорт заявок и уведомления в реальном времени.',
  ogType: 'website',
})

const { isAuthenticated, isClient } = useAuth()

// Если токен есть, а профиля нет (кука auth_user потерялась) — подтягиваем
// профиль до отрисовки, чтобы залогиненный не увидел гостевой лендинг.
const hydrating = ref(false)
onMounted(async () => {
  const a = useAuth()
  if (!a.user && a.token) {
    hydrating.value = true
    await a.fetchMe().catch(() => {})
    hydrating.value = false
  }
})

// ---------- Лендинг (гости) ----------
const advantages = [
  { icon: 'heroicons:currency-dollar', title: 'Персональные цены', text: 'Индивидуальные скидки по брендам и актуальные прайсы напрямую от менеджера.' },
  { icon: 'heroicons:bolt', title: 'Актуальный прайс', text: 'Каталог обновляется по CSV. Цены и статусы всегда свежие.' },
  { icon: 'heroicons:clipboard-document-check', title: 'Быстрые заявки', text: 'Корзина, массовое добавление по артикулам, повтор заказа в один клик.' },
  { icon: 'heroicons:document-text', title: 'Каталоги брендов', text: 'PDF-каталоги и спец-выгрузки для вашего интернет-магазина.' },
]

// ---------- Дашборд (авторизованный клиент) ----------
// seq в OrderRead может отсутствовать (бэкенд его не отдаёт) —
// formatOrderNumber сам падает обратно на короткий id.
type RecentOrder = OrderRead & { seq?: number | null }

// Маппинг статуса → бейдж, как на /orders.
const STATUS_META: Record<OrderStatus, { label: string; cls: string }> = {
  NEW: { label: 'Новая', cls: 'badge-info' },
  IN_PROGRESS: { label: 'В работе', cls: 'badge-info' },
  SHIPPED: { label: 'Отгружена', cls: 'badge-warning' },
  COMPLETED: { label: 'Завершена', cls: 'badge-success' },
  CANCELLED: { label: 'Отменена', cls: 'badge-danger' },
}

// Последние заявки: GET /api/v1/orders (как на /orders, только per_page=3).
const ordersLoading = ref(true)
const ordersFailed = ref(false)
const recentOrders = ref<RecentOrder[]>([])

// Избранное: GET /api/v1/favorites — достаточно meta.total (per_page=1).
const favLoading = ref(true)
const favFailed = ref(false)
const favTotal = ref(0)

// Файлы: GET /api/v1/files — первый элемент списка как «последний файл».
const filesLoading = ref(true)
const filesFailed = ref(false)
const lastFile = ref<FileAsset | null>(null)

// Акции/новинки: GET /api/v1/dashboard — берём только карусели товаров (fallback для баннеров).
// Баннеры: GET /api/v1/banners?position=promo|new — активные, sort ASC.
const promos = ref<ClientNewArrival[]>([])
const newArrivals = ref<ClientNewArrival[]>([])
const bannerPromo = ref<BannerRead[]>([])
const bannerNew = ref<BannerRead[]>([])

interface ClientNewArrival {
  id: string
  sku: string
  name: string
  photo_key: string | null
  client_price: string
  currency: string
  has_discount: boolean
}

// Новости: GET /api/v1/news — последние 5 штук для дашборда и лендинга.
const newsLoading = ref(true)
const newsFailed = ref(false)
const newsItems = ref<NewsRead[]>([])

function formatNewsDate(s: string): string {
  return new Date(s).toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' })
}

/** Краткий текст: первые 120 символов контента, обрезанные по слову. */
function newsExcerpt(content: string): string {
  if (content.length <= 120) return content
  const cut = content.slice(0, 120)
  const lastSpace = cut.lastIndexOf(' ')
  return (lastSpace > 60 ? cut.slice(0, lastSpace) : cut) + '…'
}

async function loadNews() {
  const { request } = useApi()
  request<NewsPage>('/api/v1/news', { query: { page: 1, per_page: 5 } })
    .then((res) => { newsItems.value = res.data })
    .catch(() => { newsFailed.value = true })
    .finally(() => { newsLoading.value = false })
}

async function loadDashboard() {
  const { request } = useApi()

  // Четыре независимых запроса: ошибка любого скрывает только свою карточку.
  request<OrderListPage>('/api/v1/orders', { query: { page: 1, per_page: 3 } })
    .then((res) => { recentOrders.value = res.data })
    .catch(() => { ordersFailed.value = true })
    .finally(() => { ordersLoading.value = false })

  request<FavoriteListPage>('/api/v1/favorites', { query: { page: 1, per_page: 1 } })
    .then((res) => { favTotal.value = res.meta.total })
    .catch(() => { favFailed.value = true })
    .finally(() => { favLoading.value = false })

  request<FileAssetPage>('/api/v1/files', { query: { page: 1, per_page: 1 } })
    .then((res) => { lastFile.value = res.data[0] ?? null })
    .catch(() => { filesFailed.value = true })
    .finally(() => { filesLoading.value = false })

  loadNews()

  // Карусели товаров: акции (товары со скидкой) и новинки — запасной вариант баннеров.
  request<{ new_arrivals?: ClientNewArrival[]; promos?: ClientNewArrival[] }>('/api/v1/dashboard')
    .then((res) => {
      promos.value = res.promos ?? []
      newArrivals.value = res.new_arrivals ?? []
    })
    .catch(() => {})

  // Маркетинговые баннеры: ошибка тихая — просто останется fallback на товары.
  // position парсится бэкендом как enum — строго в верхнем регистре.
  request<BannerRead[]>('/api/v1/banners', { query: { position: 'PROMO' } })
    .then((res) => { bannerPromo.value = res })
    .catch(() => {})
  request<BannerRead[]>('/api/v1/banners', { query: { position: 'NEW' } })
    .then((res) => { bannerNew.value = res })
    .catch(() => {})
}

onMounted(() => {
  if (isAuthenticated && isClient) {
    loadDashboard()
  } else {
    // Гости тоже видят блок новостей на лендинге.
    loadNews()
  }
})
</script>

<template>
  <div>
    <!-- Восстановление сессии: токен есть, профиль ещё не загружен — не показываем лендинг -->
    <section v-if="hydrating" class="container-app py-8 lg:py-12">
      <div class="grid grid-cols-1 md:grid-cols-3 gap-5">
        <div class="card p-5 md:col-span-2"><div class="skeleton h-32 w-full"/></div>
        <div class="card p-5"><div class="skeleton h-32 w-full"/></div>
      </div>
    </section>

    <!-- Дашборд авторизованного клиента: тот же сайдбар, что и в client layout,
         — переход в каталог доступен с главной без блока избранного -->
    <section v-else-if="isClient" class="lg:flex">
      <AppSidebar />
      <main class="flex-1 min-w-0">
      <div class="container-app py-8 lg:py-12">
      <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5 items-start lg:items-stretch">
        <!-- Левая колонка (2/3): заявки + баннеры. Баннеры растягиваются,
             чтобы нижняя граница колонки совпадала с правой (Быстрые действия). -->
        <div class="md:col-span-2 grid gap-5 content-start lg:h-full lg:flex lg:flex-col">
        <!-- Последние заявки -->
        <div v-if="!ordersFailed" class="card p-5">
          <div class="flex items-center justify-between gap-3 mb-4">
            <h3 class="text-lg font-semibold">Последние заявки</h3>
            <NuxtLink
              v-if="!ordersLoading"
              to="/orders"
              class="text-sm text-primary hover:underline whitespace-nowrap"
            >Все заявки →</NuxtLink>
          </div>

          <div v-if="ordersLoading" aria-hidden="true">
            <div v-for="i in 3" :key="i" class="skeleton h-10 w-full mb-3 last:mb-0"/>
          </div>

          <div v-else-if="!recentOrders.length" class="py-6 text-center text-ink-muted">
            <Icon name="heroicons:clipboard-document-list" class="w-10 h-10 mx-auto mb-3 text-ink-faint" />
            <p class="mb-4">Заявок пока нет</p>
            <NuxtLink to="/catalog" class="btn-primary">Перейти в каталог</NuxtLink>
          </div>

          <ul v-else class="divide-y divide-border">
            <li v-for="o in recentOrders" :key="o.id">
              <NuxtLink :to="`/orders/${o.id}`" class="flex flex-wrap items-center gap-x-3 gap-y-1.5 py-3">
                <span class="font-mono text-xs">{{ formatOrderNumber(o.seq, o.id) }}</span>
                <span class="text-sm text-ink-muted">{{ formatDate(o.created_at) }}</span>
                <span class="ml-auto text-sm font-semibold whitespace-nowrap">{{ formatMoney(o.total_amount, o.currency_code) }}</span>
                <span :class="STATUS_META[o.status].cls">{{ STATUS_META[o.status].label }}</span>
              </NuxtLink>
            </li>
          </ul>
        </div>

        <!-- Баннеры: Акции и Новинки (приоритет — баннеры, запасной вариант — товары дашборда) -->
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-5 lg:flex-1 lg:min-h-0">
          <HomeBanner
            title="Акции"
            icon="heroicons:tag"
            :banners="bannerPromo"
            :fallback="promos[0] ?? null"
            :fallback-href="promos[0] ? `/catalog/${promos[0].sku}` : '/catalog'"
          />
          <HomeBanner
            title="Новинки"
            icon="heroicons:sparkles"
            :banners="bannerNew"
            :fallback="newArrivals[0] ?? null"
            :fallback-href="newArrivals[0] ? `/catalog/${newArrivals[0].sku}` : '/catalog'"
          />
        </div>
        </div>

        <!-- Правая колонка: избранное, файлы, быстрые действия -->
        <div class="grid sm:grid-cols-2 lg:grid-cols-1 gap-5 md:col-span-2 lg:col-span-1 content-start">
        <!-- Избранное -->
        <div v-if="!favFailed" class="card p-5">
          <div class="flex items-center justify-between gap-3 mb-4">
            <h3 class="text-lg font-semibold">Избранное</h3>
            <Icon name="heroicons:heart" class="w-5 h-5 text-ink-faint" />
          </div>

          <div v-if="favLoading" aria-hidden="true">
            <div class="skeleton h-7 w-2/3 mb-3"/>
            <div class="skeleton h-9 w-full"/>
          </div>

          <template v-else-if="favTotal > 0">
            <p class="mb-4">
              <span class="text-2xl font-bold mr-1">{{ favTotal }}</span>
              {{ pluralize(favTotal, 'товар', 'товара', 'товаров') }}
            </p>
            <NuxtLink to="/favorites" class="btn-outline w-full py-2 text-sm">Открыть избранное →</NuxtLink>
          </template>

          <div v-else class="text-sm text-ink-muted">
            <p class="mb-4">Пока ничего не сохранено</p>
            <NuxtLink to="/catalog" class="btn-outline w-full py-2 text-sm">Перейти в каталог</NuxtLink>
          </div>
        </div>

        <!-- Файлы: публичного эндпоинта курса EUR для клиента нет
             (/manager/currencies/rates — только MANAGER), поэтому третья карточка — файлы. -->
        <div v-if="!filesFailed" class="card p-5">
          <div class="flex items-center justify-between gap-3 mb-4">
            <h3 class="text-lg font-semibold">Файлы</h3>
            <NuxtLink
              v-if="!filesLoading"
              to="/files"
              class="text-sm text-primary hover:underline whitespace-nowrap"
            >Все файлы →</NuxtLink>
          </div>

          <div v-if="filesLoading" aria-hidden="true">
            <div class="skeleton h-5 w-3/4 mb-2"/>
            <div class="skeleton h-4 w-1/3"/>
          </div>

          <div v-else-if="lastFile" class="flex items-start gap-3 min-w-0">
            <div class="shrink-0 w-10 h-10 rounded-card bg-secondary-soft text-secondary flex items-center justify-center">
              <Icon name="heroicons:document-arrow-down" class="w-5 h-5" />
            </div>
            <div class="min-w-0">
              <p class="font-medium truncate" :title="lastFile.filename">{{ lastFile.filename }}</p>
              <p class="text-sm text-ink-muted mt-0.5">{{ formatDate(lastFile.created_at) }}</p>
            </div>
          </div>

          <div v-else class="text-sm text-ink-muted">
            <Icon name="heroicons:folder" class="w-8 h-8 mb-2 text-ink-faint" />
            <p>Файлов пока нет</p>
          </div>
        </div>

        <!-- Быстрые действия -->
        <div class="card p-5">
          <div class="flex items-center justify-between gap-3 mb-3">
            <h3 class="text-lg font-semibold">Быстрые действия</h3>
            <Icon name="heroicons:bolt" class="w-5 h-5 text-ink-faint" />
          </div>
          <nav class="flex flex-col">
            <NuxtLink to="/catalog" class="flex items-center gap-3 py-2.5 text-sm font-medium text-ink-muted hover:text-primary transition-colors">
              <Icon name="heroicons:squares-2x2" class="w-5 h-5 shrink-0" />
              Каталог товаров
            </NuxtLink>
            <NuxtLink to="/bulk-add" class="flex items-center gap-3 py-2.5 text-sm font-medium text-ink-muted hover:text-primary transition-colors">
              <Icon name="heroicons:plus-circle" class="w-5 h-5 shrink-0" />
              Массовое добавление
            </NuxtLink>
            <NuxtLink to="/cart" class="flex items-center gap-3 py-2.5 text-sm font-medium text-ink-muted hover:text-primary transition-colors">
              <Icon name="heroicons:shopping-cart" class="w-5 h-5 shrink-0" />
              Корзина
            </NuxtLink>
            <NuxtLink to="/profile" class="flex items-center gap-3 py-2.5 text-sm font-medium text-ink-muted hover:text-primary transition-colors">
              <Icon name="heroicons:user-circle" class="w-5 h-5 shrink-0" />
              Профиль и настройки
            </NuxtLink>
          </nav>
        </div>
        </div>
      </div>

      <!-- Новости и обновления (под основным контентом, полная ширина) -->
      <div v-if="!newsFailed && (newsLoading || newsItems.length)" class="mt-8">
        <div class="flex items-center justify-between gap-3 mb-4">
          <h3 class="text-lg font-semibold">Новости и обновления</h3>
          <Icon name="heroicons:newspaper" class="w-5 h-5 text-ink-faint" />
        </div>

        <!-- Skeleton -->
        <div v-if="newsLoading" class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
          <div v-for="i in 3" :key="i" class="card p-5">
            <div class="skeleton h-3 w-1/3 mb-3" />
            <div class="skeleton h-5 w-full mb-2" />
            <div class="skeleton h-3 w-2/3" />
          </div>
        </div>

        <!-- Карточки новостей -->
        <div v-else class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
          <NuxtLink v-for="item in newsItems" :key="item.id" :to="`/news/${item.id}`">
            <article class="card card-hover p-5 h-full">
              <div class="flex items-center gap-2 mb-2">
                <span v-if="item.type === 'NEW_PRODUCT'" class="badge-success text-xs">Новинка</span>
                <span v-else class="badge-info text-xs">Новость</span>
                <span class="text-xs text-ink-muted">{{ formatNewsDate(item.published_at) }}</span>
              </div>
              <h4 class="font-semibold mb-2 leading-snug hover:text-primary transition-colors">{{ item.title }}</h4>
              <p class="text-sm text-ink-muted leading-relaxed">{{ newsExcerpt(item.content) }}</p>
            </article>
          </NuxtLink>
        </div>
      </div>
      </div>
      </main>
    </section>

    <!-- Лендинг для гостей: без изменений -->
    <template v-else>
      <!-- Hero -->
      <section class="relative overflow-hidden">
        <div class="container-app py-16 lg:py-24 text-center">
          <span class="chip bg-primary-soft text-primary mb-6">B2B-портал</span>
          <h1 class="text-3xl sm:text-4xl lg:text-5xl font-bold mb-5 leading-tight">
            Персональный доступ к прайсам<br class="hidden sm:block" >
            и управлению заявками
          </h1>
          <p class="text-lg text-ink-muted max-w-2xl mx-auto mb-8">
            Личный кабинет с динамическими ценами по вашему договору, импорт заявок и уведомления в реальном времени.
          </p>
          <div class="flex flex-wrap items-center justify-center gap-3">
            <NuxtLink
              v-if="isAuthenticated"
              to="/catalog"
              class="btn-primary px-6 py-3 text-base"
            >Перейти в каталог</NuxtLink>
            <NuxtLink
              v-else
              to="/login"
              class="btn-primary px-6 py-3 text-base"
            >Войти в личный кабинет</NuxtLink>
            <a href="#" class="btn-outline px-6 py-3 text-base">Связаться с менеджером</a>
          </div>
        </div>
      </section>

      <!-- Преимущества -->
      <section class="container-app py-12 lg:py-16">
        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
          <div v-for="a in advantages" :key="a.title" class="card card-hover p-6">
            <div class="w-12 h-12 rounded-card bg-primary-soft text-primary flex items-center justify-center mb-4">
              <Icon :name="a.icon" class="w-6 h-6" />
            </div>
            <h3 class="text-lg font-semibold mb-2">{{ a.title }}</h3>
            <p class="text-sm text-ink-muted leading-relaxed">{{ a.text }}</p>
          </div>
        </div>
      </section>

      <!-- Новости (гости) -->
      <section v-if="!newsFailed && (newsLoading || newsItems.length)" class="container-app py-12 lg:py-16">
        <h2 class="text-2xl font-bold text-center mb-8">Новости и обновления</h2>
        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
          <!-- Skeleton -->
          <template v-if="newsLoading">
            <div v-for="i in 3" :key="i" class="card p-5">
              <div class="skeleton h-3 w-1/3 mb-3" />
              <div class="skeleton h-5 w-full mb-2" />
              <div class="skeleton h-3 w-2/3" />
            </div>
          </template>

          <!-- Карточки -->
          <template v-else>
            <NuxtLink v-for="item in newsItems.slice(0, 6)" :key="item.id" :to="`/news/${item.id}`">
              <article class="card card-hover p-5 h-full">
                <div class="flex items-center gap-2 mb-2">
                  <span v-if="item.type === 'NEW_PRODUCT'" class="badge-success text-xs">Новинка</span>
                  <span v-else class="badge-info text-xs">Новость</span>
                  <span class="text-xs text-ink-muted">{{ formatNewsDate(item.published_at) }}</span>
                </div>
                <h3 class="font-semibold mb-2 leading-snug hover:text-primary transition-colors">{{ item.title }}</h3>
                <p class="text-sm text-ink-muted leading-relaxed">{{ newsExcerpt(item.content) }}</p>
              </article>
            </NuxtLink>
          </template>
        </div>
      </section>

      <!-- Как начать -->
      <section class="bg-surface border-y border-border">
        <div class="container-app py-12 lg:py-16">
          <h2 class="text-2xl font-bold text-center mb-10">Как начать работу</h2>
          <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div
v-for="(step, i) in [
              { t: 'Менеджер создаёт аккаунт', d: 'Вы получаете логин и временный пароль от вашего персонального менеджера.' },
              { t: 'Вход и согласие', d: 'Первый вход — принимаете условия обработки персональных данных.' },
              { t: 'Заказ и отслеживание', d: 'Собираете корзину, оформляете заявку и следите за статусом в реальном времени.' },
            ]" :key="i" class="flex gap-4">
              <div class="shrink-0 w-10 h-10 rounded-pill bg-secondary-soft text-secondary flex items-center justify-center font-bold">{{ i + 1 }}</div>
              <div>
                <h4 class="font-semibold mb-1">{{ step.t }}</h4>
                <p class="text-sm text-ink-muted">{{ step.d }}</p>
              </div>
            </div>
          </div>
        </div>
      </section>
    </template>
  </div>
</template>
