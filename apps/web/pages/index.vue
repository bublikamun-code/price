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

// SEO лендинга: ключевая страница для индексации (§6, SITEMAP §5).
// Канонический URL и og:image — абсолютные, от хоста запроса (SSR).
const pageOrigin = useRequestURL().origin
const pageUrl = `${pageOrigin}/`
useHead({
  title: 'B2B-портал светотехники и электромонтажа — персональные цены и заявки онлайн',
  titleTemplate: '%s',
  link: [{ rel: 'canonical', href: pageUrl }],
  script: [
    {
      // JSON-LD: Organization + WebSite + FAQPage (rich results Яндекса/Google).
      // Вопросы должны оставаться синхронны видимому FAQ-блоку ниже на странице.
      type: 'application/ld+json',
      innerHTML: JSON.stringify([
        {
          '@context': 'https://schema.org',
          '@type': 'Organization',
          name: 'ООО «Свет в доме»',
          url: pageOrigin,
          telephone: '+375 (29) 123-45-67',
          email: 'info@svetvdome.by',
          address: {
            '@type': 'PostalAddress',
            addressCountry: 'BY',
            addressLocality: 'Минск',
            streetAddress: 'ул. Примерная, д. 1, офис 1',
          },
        },
        {
          '@context': 'https://schema.org',
          '@type': 'WebSite',
          name: 'PricePortal',
          url: pageOrigin,
          inLanguage: 'ru',
        },
        {
          '@context': 'https://schema.org',
          '@type': 'FAQPage',
          mainEntity: [
            'Как формируются мои цены?|Прайс-лист импортируется в портал, а к нему применяется ваша персональная скидка по договору. Вы видите свою цену у каждого товара после входа — общих цен и «витринных наценок» на портале нет.',
            'Посмотреть каталог можно без регистрации?|Да. Номенклатура, характеристики и состав склада открыты всем. Цены, корзина и оформление заявок — после входа в кабинет.',
            'Как быстро подтверждается заявка?|Заявка сразу попадает менеджеру в кабинет со всеми позициями и комментарием. Вы меняете статусы в реальном времени — без звонков для уточнения деталей.',
            'Что нужно для начала работы?|Оставьте заявку на этой странице или позвоните. Менеджер согласует условия, создаст аккаунт и передаст вам логин и временный пароль.',
          ].map((qa) => {
            const [q, a] = qa.split('|')
            return {
              '@type': 'Question',
              name: q,
              acceptedAnswer: { '@type': 'Answer', text: a },
            }
          }),
        },
      ]),
    },
  ],
})
useSeoMeta({
  description:
    'Каталог KEAZ, SmartWatt и Rostok: корпуса, щиты, стабилизаторы напряжения, реле напряжения. Персональные цены по договору, заявки онлайн, статусы в реальном времени. Работаем с юридическими лицами и ИП.',
  ogTitle: 'PricePortal — персональные цены и заявки для юридических лиц',
  ogDescription:
    'Каталог светотехники и электромонтажа с открытым составом склада. Цены по вашему договору, заявки и статусы — онлайн.',
  ogType: 'website',
  ogUrl: pageUrl,
  ogImage: `${pageOrigin}/og-landing.png`,
  ogImageWidth: 1200,
  ogImageHeight: 630,
  twitterCard: 'summary_large_image',
})

// storeToRefs обязателен: деструктуризация Pinia-стора напрямую даёт
// снапшот-булевы значения без реактивности — сессия, восстановленная ПОСЛЕ
// монтирования (fetchMe в плагине auth.session), не была видна ни скрипту,
// ни шаблону, и карточки дашборда оставались в скелетонах навсегда.
const auth = useAuth()
const { isAuthenticated, isClient } = storeToRefs(auth)

// Если токен есть, а профиля нет (кука auth_user потерялась) — подтягиваем
// профиль до отрисовки, чтобы залогиненный не увидел гостевой лендинг.
const hydrating = ref(false)
const showContactModal = ref(false)
onMounted(async () => {
  const a = useAuth()
  if (!a.user && a.token) {
    hydrating.value = true
    await a.fetchMe().catch(() => {})
    hydrating.value = false
  }
})

// ---------- Лендинг (гости) ----------

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

  requestNewsOnce()

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

// Загрузка привязана к состоянию сессии через watch (а не onMounted): сессия
// может восстановиться ПОСЛЕ монтирования страницы (refresh, потерянная кука
// auth_user, гонка 401 → refresh в плагине auth.session). immediate-режим
// покрывает и уже восстановленную сессию, и гостя при первом рендере.
// Гварды ниже не дают задвоить запросы (сценарий: старт как «гость» без профиля
// → loadNews, затем fetchMe подтвердил клиента → loadDashboard).
let dashboardRequested = false
let newsRequested = false

function requestNewsOnce() {
  if (newsRequested) return
  newsRequested = true
  loadNews()
}

// Витрина лендинга (публичные данные, без входа): бренды с фото и счётчиками.
interface ShowcaseBrand { name: string; slug: string; photo?: string; seriesCount: number; productsCount: number }
// Товары витрины: публичные данные без цен (цены — персональные, после входа).
interface ShowcaseProduct { sku: string; name: string; photo?: string; brandName: string; brandSlug: string }
const showcaseLoading = ref(true)
const showcaseFailed = ref(false)
const showcaseBrands = ref<ShowcaseBrand[]>([])
const showcaseProducts = ref<ShowcaseProduct[]>([])

// Какими товарами бренд представляется на лендинге: названия с этими словами
// поднимаются наверх витрины (KEAZ показываем корпусами-щитами, не аксессуарами).
const BRAND_SHOWCASE_KEYWORDS: Record<string, string[]> = {
  keaz: ['корпус', 'щит', 'шкаф'],
}

function showcasePhotoUrl(key?: string): string | undefined {
  if (!key) return undefined
  // §16 п.17: http(s)-значения — внешние ссылки (напрямую), остальное — S3-ключи.
  if (/^https?:\/\//.test(key)) return key
  return `/api/v1/public/photo?key=${encodeURIComponent(key)}`
}

// Клиентская загрузка (не useAsyncData): $api-перехватчик зовёт useCookie,
// чей Nuxt-контекст внутри хендлера useAsyncData недоступен.
async function loadShowcase() {
  const { request } = useApi()
  let brands: ShowcaseBrand[] = []
  try {
    const res = await request<{
      data: { name: string; slug: string; photo?: string; series_count: number; products_count: number }[]
    }>('/api/v1/public/brands')
    brands = res.data.map((b) => ({
      name: b.name,
      slug: b.slug,
      photo: b.photo,
      seriesCount: b.series_count,
      productsCount: b.products_count,
    }))
    showcaseBrands.value = brands
  } catch {
    showcaseFailed.value = true
    showcaseLoading.value = false
    return
  }
  // Витрина товаров: первая серия каждого из первых 3 брендов (публичные
  // данные, без цен). Фейл одной ветки не ломает лендинг — allSettled.
  const perBrand = 60
  const shownPerBrand = 8
  const results = await Promise.allSettled(
    brands.slice(0, 3).map(async (b): Promise<ShowcaseProduct[]> => {
      const detail = await request<{ data: { series?: { slug: string }[] } }>(
        `/api/v1/public/brands/${encodeURIComponent(b.slug)}`,
      )
      const seriesSlug = detail.data?.series?.[0]?.slug
      if (!seriesSlug) return []
      const pr = await request<{ data: { sku: string; name: string; photo?: string }[] }>(
        `/api/v1/public/series/${encodeURIComponent(seriesSlug)}/products?page=1&per_page=${perBrand}`,
      )
      const kw = BRAND_SHOWCASE_KEYWORDS[b.slug] ?? []
      let items = pr.data
      if (kw.length) {
        const rank = (n: string) => (kw.some((k) => n.toLowerCase().includes(k)) ? 0 : 1)
        items = [...items].sort((a, c) => rank(a.name) - rank(c.name))
      }
      return items.slice(0, shownPerBrand).map((p) => ({
        sku: p.sku,
        name: p.name,
        photo: p.photo,
        brandName: b.name,
        brandSlug: b.slug,
      }))
    }),
  )
  // Чередуем бренды (round-robin), чтобы витрина не начиналась
  // с нескольких похожих товаров одной серии.
  const lists = results
    .filter((r): r is PromiseFulfilledResult<ShowcaseProduct[]> => r.status === 'fulfilled')
    .map((r) => r.value)
  const interleaved: ShowcaseProduct[] = []
  for (let i = 0; ; i++) {
    let any = false
    for (const list of lists) {
      if (list[i]) {
        interleaved.push(list[i])
        any = true
      }
    }
    if (!any) break
  }
  showcaseProducts.value = interleaved
  showcaseLoading.value = false
}

let showcaseRequested = false
function requestShowcaseOnce() {
  if (showcaseRequested) return
  showcaseRequested = true
  loadShowcase()
}

// Итоги для hero-чипов лендинга (считаются из витрины брендов).
const showcaseTotals = computed(() => ({
  brands: showcaseBrands.value.length,
  series: showcaseBrands.value.reduce((s, b) => s + b.seriesCount, 0),
  products: showcaseBrands.value.reduce((s, b) => s + b.productsCount, 0),
}))

// Коллаж в hero: первые фото товаров витрины (фолбэк — фото брендов).
const heroShots = computed(() => {
  const shots: { src?: string; label: string }[] = showcaseProducts.value
    .filter((p) => p.photo)
    .slice(0, 3)
    .map((p) => ({ src: showcasePhotoUrl(p.photo), label: p.brandName }))
  for (const b of showcaseBrands.value) {
    if (shots.length < 3 && b.photo) shots.push({ src: showcasePhotoUrl(b.photo), label: b.name })
  }
  return shots
})

// Горизонтальная прокрутка витрины товаров (стрелки).
const productRow = ref<HTMLElement | null>(null)
function scrollProducts(dir: -1 | 1) {
  productRow.value?.scrollBy({ left: dir * 660, behavior: 'smooth' })
}

// Лид-форма лендинга: заявка на доступ уходит менеджерам (POST /public/lead).
const leadForm = reactive({
  company: '',
  contact_name: '',
  phone: '',
  email: '',
  comment: '',
  website: '',  // honeypot — скрытое поле против ботов
})
const leadSubmitting = ref(false)
const leadSuccess = ref(false)
const leadError = ref('')
const leadValid = computed(
  () =>
    leadForm.company.trim().length >= 2 &&
    leadForm.contact_name.trim().length >= 2 &&
    leadForm.phone.trim().length >= 7,
)

async function submitLead() {
  if (!leadValid.value || leadSubmitting.value) return
  leadSubmitting.value = true
  leadError.value = ''
  try {
    const { request } = useApi()
    await request('/api/v1/public/lead', {
      method: 'POST',
      body: {
        company: leadForm.company.trim(),
        contact_name: leadForm.contact_name.trim(),
        phone: leadForm.phone.trim(),
        email: leadForm.email.trim() || undefined,
        comment: leadForm.comment.trim() || undefined,
        website: leadForm.website,
      },
    })
    leadSuccess.value = true
  } catch (e) {
    leadError.value = getErrorMessage(e, 'Не удалось отправить заявку. Позвоните нам — контакты ниже.')
  } finally {
    leadSubmitting.value = false
  }
}

function scrollToLead() {
  document.getElementById('lead')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

watch(
  [isAuthenticated, isClient],
  ([authed, clientRole]) => {
    if (authed && clientRole) {
      if (!dashboardRequested) {
        dashboardRequested = true
        loadDashboard()
      }
    } else {
      // Гости и менеджеры тоже видят блоки новостей и продукции на лендинге.
      requestNewsOnce()
      requestShowcaseOnce()
    }
  },
  { immediate: true },
)
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
    <section v-else-if="isClient" class="lg:flex lg:justify-center">
      <div class="container-app lg:flex">
      <AppSidebar />
      <main class="flex-1 min-w-0 py-8 lg:py-12">
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
      </main>
      </div>
    </section>

    <!-- Лендинг для гостей (SITEMAP §5): hero с коллажем фото, витрина товаров,
         бренды, возможности кабинета, новости, о компании, шаги, финальный CTA -->
    <template v-else>
      <!-- HERO -->
      <section class="relative overflow-hidden min-h-[85vh] flex items-center">
        <div class="container-app py-20 lg:py-28 w-full">
          <div class="grid lg:grid-cols-2 gap-16 items-center">
            <div class="text-center lg:text-left">
              <span class="chip bg-primary-soft text-primary mb-8">B2B-портал · светотехника и электромонтаж</span>
              <h1 class="text-4xl sm:text-5xl lg:text-6xl xl:text-7xl font-bold leading-[1.08] tracking-tight mb-8">
                Персональные прайсы<br class="hidden lg:block">
                и&nbsp;заявки —<br class="hidden lg:block">
                в одном кабинете
              </h1>
              <p class="text-lg lg:text-xl text-ink-muted max-w-lg mx-auto lg:mx-0 mb-10 leading-relaxed">
                Цены по вашему договору, состав склада, заявки и статусы — онлайн.
                Без звонков и переписок.
              </p>
              <div class="flex flex-wrap items-center justify-center lg:justify-start gap-4">
                <button
                  v-if="!isAuthenticated"
                  type="button"
                  class="btn-accent px-8 py-4 text-base"
                  @click="scrollToLead"
                >Получить доступ и прайс</button>
                <NuxtLink
                  v-else
                  to="/catalog"
                  class="btn-accent px-8 py-4 text-base"
                >Перейти в каталог</NuxtLink>
                <NuxtLink to="/login" class="btn-outline px-8 py-4 text-base">Войти в кабинет</NuxtLink>
              </div>
            </div>

            <!-- Photo collage -->
            <div v-if="heroShots.length" class="relative hidden lg:block h-[480px]" aria-hidden="true">
              <div
                v-for="(s, i) in heroShots"
                :key="i"
                class="card absolute w-64 p-4 transition-transform duration-500"
                :class="[
                  i === 0 ? 'left-0 top-12 -rotate-3 z-10' : '',
                  i === 1 ? 'right-0 top-0 rotate-2 z-20' : '',
                  i === 2 ? 'left-1/2 -translate-x-1/2 bottom-0 rotate-1 z-30' : '',
                ]"
              >
                <div class="relative aspect-[4/3] bg-white rounded-[18px] flex items-center justify-center overflow-hidden">
                  <img v-if="s.src" :src="s.src" :alt="s.label" class="w-full h-full object-contain" loading="eager">
                  <Icon v-else name="heroicons:photo" class="w-10 h-10 text-ink-faint" />
                  <span class="badge badge-solid absolute top-2 left-2">{{ s.label }}</span>
                </div>
              </div>
            </div>
            <!-- Mobile: simple row -->
            <div v-if="heroShots.length" class="grid grid-cols-3 gap-3 mt-8 lg:hidden" aria-hidden="true">
              <div v-for="(s, i) in heroShots" :key="i" class="card p-2">
                <div class="relative aspect-square bg-white rounded-[18px] flex items-center justify-center overflow-hidden">
                  <img v-if="s.src" :src="s.src" :alt="s.label" class="w-full h-full object-contain" loading="eager">
                  <span class="badge badge-solid absolute top-1.5 left-1.5">{{ s.label }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <LandingMetrics
        :products-count="showcaseTotals.products || undefined"
        :brands-count="showcaseTotals.brands || undefined"
      />

      <!-- Товары из каталога: горизонтальная витрина (публичные данные, без цен) -->
      <section v-if="showcaseProducts.length" class="py-16 lg:py-20">
        <div class="container-app">
          <div class="flex items-end justify-between gap-4 mb-8">
            <div>
              <p class="text-xs font-semibold uppercase tracking-[0.2em] text-ink-faint mb-2">Каталог</p>
              <h2 class="text-3xl font-bold">Товары из каталога</h2>
              <p class="text-sm text-ink-muted mt-2 max-w-2xl">
                Характеристики каждого товара открыты всем.
                Цены персональные — увидите их после входа в кабинет.
              </p>
            </div>
            <div class="hidden sm:flex items-center gap-2 shrink-0">
              <button type="button" class="btn-outline p-2.5 rounded-pill" aria-label="Прокрутить назад" @click="scrollProducts(-1)">
                <Icon name="heroicons:chevron-left" class="w-5 h-5" />
              </button>
              <button type="button" class="btn-outline p-2.5 rounded-pill" aria-label="Прокрутить вперёд" @click="scrollProducts(1)">
                <Icon name="heroicons:chevron-right" class="w-5 h-5" />
              </button>
            </div>
          </div>

          <div
            ref="productRow"
            class="flex gap-5 overflow-x-auto snap-x scroll-smooth pb-2 scrollbar-none -mx-4 px-4 lg:mx-0 lg:px-0"
          >
            <NuxtLink
              v-for="p in showcaseProducts"
              :key="`${p.brandSlug}-${p.sku}`"
              :to="`/catalog/${p.sku}`"
              class="card card-hover overflow-hidden group flex flex-col w-60 sm:w-64 shrink-0 snap-start"
            >
              <div class="aspect-[4/3] bg-white flex items-center justify-center overflow-hidden">
                <img
                  v-if="p.photo"
                  :src="showcasePhotoUrl(p.photo)"
                  :alt="p.name"
                  class="w-full h-full object-contain p-4 transition-transform duration-300 group-hover:scale-105"
                  loading="lazy"
                >
                <Icon v-else name="heroicons:cube" class="w-10 h-10 text-ink-faint" />
              </div>
              <div class="p-4 flex flex-col gap-2 flex-1">
                <span class="badge-info self-start">{{ p.brandName }}</span>
                <h3 class="text-sm font-medium leading-snug line-clamp-2">{{ p.name }}</h3>
                <div class="mt-auto flex items-center justify-between gap-2 pt-1">
                  <span class="text-xs text-ink-faint truncate">Арт. {{ p.sku }}</span>
                  <Icon
                    name="heroicons:arrow-right"
                    class="w-4 h-4 text-ink-faint group-hover:text-primary group-hover:translate-x-0.5 transition-all duration-200 shrink-0"
                  />
                </div>
              </div>
            </NuxtLink>
          </div>

          <div class="text-center mt-8">
            <NuxtLink to="/brands" class="btn-outline px-5 py-2.5 text-sm inline-flex items-center gap-2">
              Весь каталог
              <Icon name="heroicons:arrow-right" class="w-4 h-4" />
            </NuxtLink>
          </div>
        </div>
      </section>

      <!-- Сравнение -->
      <section class="py-20 lg:py-28">
        <div class="container-app">
          <h2 class="text-3xl lg:text-4xl font-bold text-center mb-4">Заказ без портала и с порталом</h2>
          <p class="text-ink-muted text-center max-w-xl mx-auto mb-12">
            Как меняется процесс закупки, когда всё в одном кабинете
          </p>
          <div class="grid md:grid-cols-2 gap-6 max-w-4xl mx-auto">
            <div class="card p-8">
              <h3 class="text-lg font-semibold mb-5 text-ink-muted">Как обычно</h3>
              <ul class="space-y-4 text-sm text-ink-muted">
                <li class="flex items-start gap-3">
                  <Icon name="heroicons:x-mark" class="w-5 h-5 text-ink-faint shrink-0 mt-0.5" />
                  Цены уточняются по телефону или в переписке
                </li>
                <li class="flex items-start gap-3">
                  <Icon name="heroicons:x-mark" class="w-5 h-5 text-ink-faint shrink-0 mt-0.5" />
                  Заявка в почте — легко ошибиться в артикуле
                </li>
                <li class="flex items-start gap-3">
                  <Icon name="heroicons:x-mark" class="w-5 h-5 text-ink-faint shrink-0 mt-0.5" />
                  Статус неизвестен: «а что там с моей заявкой?»
                </li>
                <li class="flex items-start gap-3">
                  <Icon name="heroicons:x-mark" class="w-5 h-5 text-ink-faint shrink-0 mt-0.5" />
                  История заказов размазана по почте и чатам
                </li>
              </ul>
            </div>
            <div class="card card-solid p-8">
              <h3 class="text-lg font-semibold mb-5">На портале</h3>
              <ul class="space-y-4 text-sm">
                <li class="flex items-start gap-3">
                  <Icon name="heroicons:check" class="w-5 h-5 text-success shrink-0 mt-0.5" />
                  Ваша цена видна прямо у товара — по договору
                </li>
                <li class="flex items-start gap-3">
                  <Icon name="heroicons:check" class="w-5 h-5 text-success shrink-0 mt-0.5" />
                  Корзина из каталога: артикулы уже верные
                </li>
                <li class="flex items-start gap-3">
                  <Icon name="heroicons:check" class="w-5 h-5 text-success shrink-0 mt-0.5" />
                  Статусы заявки меняются в реальном времени
                </li>
                <li class="flex items-start gap-3">
                  <Icon name="heroicons:check" class="w-5 h-5 text-success shrink-0 mt-0.5" />
                  Все заявки, файлы и уведомления — в одном кабинете
                </li>
              </ul>
            </div>
          </div>
        </div>
      </section>

      <!-- Лид-форма -->
      <section id="lead" class="scroll-mt-6 py-20 lg:py-28">
        <div class="container-app max-w-2xl mx-auto">
          <div v-reveal class="card p-8 lg:p-12">
            <div class="text-center mb-8">
              <h2 class="text-3xl lg:text-4xl font-bold mb-3">Получить доступ и прайс</h2>
              <p class="text-ink-muted">
                Оставьте заявку — менеджер создаст аккаунт и настроит цены по вашему договору.
                Отвечаем в течение 2 часов в рабочее время.
              </p>
            </div>

            <div v-if="leadSuccess" class="flex flex-col items-center text-center py-8">
              <Icon name="heroicons:check-badge" class="w-14 h-14 text-success mb-4" />
              <h3 class="text-xl font-bold mb-2">Заявка отправлена</h3>
              <p class="text-sm text-ink-muted">Менеджер свяжется с вами в ближайшее рабочее время.</p>
            </div>

            <form v-else class="space-y-4" @submit.prevent="submitLead">
              <input v-model="leadForm.website" type="text" class="hidden" tabindex="-1" autocomplete="off" aria-hidden="true">
              <div class="grid sm:grid-cols-2 gap-4">
                <div>
                  <label class="label" for="lead-company">Компания <span class="text-danger">*</span></label>
                  <input id="lead-company" v-model="leadForm.company" type="text" class="input" placeholder="ООО «Пример»" required minlength="2" maxlength="255">
                </div>
                <div>
                  <label class="label" for="lead-name">Контактное лицо <span class="text-danger">*</span></label>
                  <input id="lead-name" v-model="leadForm.contact_name" type="text" class="input" placeholder="Иванов Иван" required minlength="2" maxlength="255">
                </div>
              </div>
              <div class="grid sm:grid-cols-2 gap-4">
                <div>
                  <label class="label" for="lead-phone">Телефон <span class="text-danger">*</span></label>
                  <input id="lead-phone" v-model="leadForm.phone" type="tel" class="input" placeholder="+375 29 000-00-00" required minlength="7" maxlength="32">
                </div>
                <div>
                  <label class="label" for="lead-email">Email</label>
                  <input id="lead-email" v-model="leadForm.email" type="email" class="input" placeholder="you@company.by" maxlength="255">
                </div>
              </div>
              <div>
                <label class="label" for="lead-comment">Что вас интересует?</label>
                <textarea id="lead-comment" v-model="leadForm.comment" class="input min-h-24 resize-y" placeholder="Напр.: прайс на корпуса OptiBox Pro, регулярные поставки" maxlength="1000" />
              </div>
              <div v-if="leadError" class="badge-danger w-full justify-center py-2">{{ leadError }}</div>
              <button type="submit" class="btn-accent w-full justify-center py-4 text-base" :disabled="leadSubmitting || !leadValid">
                {{ leadSubmitting ? 'Отправка…' : 'Отправить заявку' }}
              </button>
              <p class="text-xs text-ink-faint text-center">
                Отправляя заявку, вы соглашаетесь на обработку данных.
              </p>
            </form>
          </div>
        </div>
      </section>

      <LandingTestimonials />

      <!-- FAQ + Start steps + Contacts -->
      <section class="bg-surface border-t border-border py-20 lg:py-28">
        <div class="container-app">
          <!-- FAQ -->
          <div class="max-w-2xl mx-auto mb-20">
            <h2 class="text-2xl font-bold text-center mb-8">Частые вопросы</h2>
            <div class="space-y-3">
              <details class="card p-5 group">
                <summary class="flex items-center justify-between gap-4 cursor-pointer font-semibold list-none">
                  Как формируются мои цены?
                  <Icon name="heroicons:chevron-down" class="w-5 h-5 text-ink-faint group-open:rotate-180 transition-transform shrink-0" />
                </summary>
                <p class="text-sm text-ink-muted leading-relaxed mt-3">
                  Прайс-лист импортируется в портал, а к нему применяется ваша персональная
                  скидка по договору. Вы видите свою цену у каждого товара после входа.
                </p>
              </details>
              <details class="card p-5 group">
                <summary class="flex items-center justify-between gap-4 cursor-pointer font-semibold list-none">
                  Посмотреть каталог можно без регистрации?
                  <Icon name="heroicons:chevron-down" class="w-5 h-5 text-ink-faint group-open:rotate-180 transition-transform shrink-0" />
                </summary>
                <p class="text-sm text-ink-muted leading-relaxed mt-3">
                  Да. Номенклатура, характеристики и состав склада открыты всем.
                  Цены, корзина и заявки — после входа в кабинет.
                </p>
              </details>
              <details class="card p-5 group">
                <summary class="flex items-center justify-between gap-4 cursor-pointer font-semibold list-none">
                  Как быстро подтверждается заявка?
                  <Icon name="heroicons:chevron-down" class="w-5 h-5 text-ink-faint group-open:rotate-180 transition-transform shrink-0" />
                </summary>
                <p class="text-sm text-ink-muted leading-relaxed mt-3">
                  Заявка сразу попадает менеджеру. Статусы меняются в реальном времени —
                  без звонков для уточнения деталей.
                </p>
              </details>
              <details class="card p-5 group">
                <summary class="flex items-center justify-between gap-4 cursor-pointer font-semibold list-none">
                  Что нужно для начала работы?
                  <Icon name="heroicons:chevron-down" class="w-5 h-5 text-ink-faint group-open:rotate-180 transition-transform shrink-0" />
                </summary>
                <p class="text-sm text-ink-muted leading-relaxed mt-3">
                  Оставьте заявку или позвоните. Менеджер создаст аккаунт и передаст
                  логин и временный пароль.
                </p>
              </details>
            </div>
          </div>

          <!-- How to start -->
          <div class="max-w-2xl mx-auto mb-16">
            <h2 class="text-2xl font-bold text-center mb-10">Как начать</h2>
            <div class="grid grid-cols-1 md:grid-cols-3 gap-6 text-center">
              <div class="flex flex-col items-center">
                <div class="w-10 h-10 rounded-pill bg-primary text-white flex items-center justify-center font-bold mb-3">1</div>
                <h4 class="font-semibold mb-1">Менеджер создаёт аккаунт</h4>
                <p class="text-sm text-ink-muted">Логин и временный пароль от вашего менеджера.</p>
              </div>
              <div class="flex flex-col items-center">
                <div class="w-10 h-10 rounded-pill bg-primary text-white flex items-center justify-center font-bold mb-3">2</div>
                <h4 class="font-semibold mb-1">Вход и согласие</h4>
                <p class="text-sm text-ink-muted">Принимаете условия обработки данных.</p>
              </div>
              <div class="flex flex-col items-center">
                <div class="w-10 h-10 rounded-pill bg-primary text-white flex items-center justify-center font-bold mb-3">3</div>
                <h4 class="font-semibold mb-1">Заказ и отслеживание</h4>
                <p class="text-sm text-ink-muted">Корзина, заявка, статусы в реальном времени.</p>
              </div>
            </div>
          </div>

          <!-- Contacts (compact) -->
          <div class="flex flex-wrap items-center justify-center gap-x-8 gap-y-2 text-sm text-ink-muted">
            <span class="font-semibold text-ink">ООО «Свет в доме»</span>
            <a href="tel:+375291234567" class="hover:text-primary transition-colors">+375 (29) 123-45-67</a>
            <a href="mailto:info@svetvdome.by" class="hover:text-primary transition-colors">info@svetvdome.by</a>
            <span>Минск</span>
            <button type="button" class="btn-accent px-4 py-2 text-xs" @click="showContactModal = true">
              Связаться
            </button>
          </div>
        </div>
      </section>

    </template>

    <ManagerContactModal :show="showContactModal" @close="showContactModal = false" />
  </div>
</template>
