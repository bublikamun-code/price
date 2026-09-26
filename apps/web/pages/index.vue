<script setup lang="ts">
import { COMPANY_NAME } from '~/utils/site'

interface ShowcaseBrand {
  name: string
  slug: string
  photo?: string
  seriesCount: number
  productsCount: number
}

const FAQ_ITEMS = [
  {
    question: 'Как формируются мои цены?',
    answer: 'Прайс-лист импортируется в портал, а к нему применяется ваша персональная скидка по договору. Вы видите свою цену у каждого товара после входа — общих цен и «витринных наценок» на портале нет.',
  },
  {
    question: 'Посмотреть каталог можно без регистрации?',
    answer: 'Да. Номенклатура, характеристики и состав склада открыты всем. Цены, корзина и оформление заявок — после входа в кабинет.',
  },
  {
    question: 'Как быстро подтверждается заявка?',
    answer: 'Заявка сразу попадает менеджеру в кабинет со всеми позициями и комментарием. Вы меняете статусы в реальном времени — без звонков для уточнения деталей.',
  },
  {
    question: 'Что нужно для начала работы?',
    answer: 'Оставьте заявку на этой странице. Менеджер согласует условия, создаст аккаунт и передаст вам логин и временный пароль.',
  },
] as const

const pageOrigin = useRequestURL().origin
const pageUrl = `${pageOrigin}/`

useHead({
  title: 'B2B-портал светотехники и электромонтажа — персональные цены и заявки онлайн',
  titleTemplate: '%s',
  link: [{ rel: 'canonical', href: pageUrl }],
  script: [
    {
      type: 'application/ld+json',
      innerHTML: JSON.stringify([
        {
          '@context': 'https://schema.org',
          '@type': 'Organization',
          name: COMPANY_NAME,
          url: pageOrigin,
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
          mainEntity: FAQ_ITEMS.map((item) => ({
            '@type': 'Question',
            name: item.question,
            acceptedAnswer: { '@type': 'Answer', text: item.answer },
          })),
        },
      ]),
    },
  ],
})

useSeoMeta({
  description: 'Каталог KEAZ, SmartWatt и Rostok: корпуса, щиты, стабилизаторы напряжения, реле напряжения. Персональные цены по договору, заявки онлайн, статусы в реальном времени. Работаем с юридическими лицами и ИП.',
  ogTitle: 'PricePortal — персональные цены и заявки для юридических лиц',
  ogDescription: 'Каталог светотехники и электромонтажа с открытым составом склада. Цены по вашему договору, заявки и статусы — онлайн.',
  ogType: 'website',
  ogUrl: pageUrl,
  ogImage: `${pageOrigin}/og-landing.png`,
  ogImageWidth: 1200,
  ogImageHeight: 630,
  twitterCard: 'summary_large_image',
})

const auth = useAuth()
const { isAuthenticated, isManager } = storeToRefs(auth)
const { request } = useApi()

const showContactModal = ref(false)
const showcaseLoading = ref(true)
const showcaseFailed = ref(false)
const showcaseBrands = ref<ShowcaseBrand[]>([])
const catalogDate = ref('')

const primaryCatalogPath = computed(() => {
  if (isManager.value) return '/manager'
  if (isAuthenticated.value) return '/catalog'
  return '/brands'
})

const accountPath = computed(() => {
  if (isManager.value) return '/manager'
  if (isAuthenticated.value) return '/dashboard'
  return '/login'
})

const heroBrands = computed(() => showcaseBrands.value.slice(0, 3))
const catalogRows = computed(() => showcaseBrands.value.slice(0, 8))
const wallBrands = computed(() => showcaseBrands.value.slice(0, 6))

const catalogStats = computed(() => ({
  brands: showcaseBrands.value.length,
  series: showcaseBrands.value.reduce((total, brand) => total + brand.seriesCount, 0),
  products: showcaseBrands.value.reduce((total, brand) => total + brand.productsCount, 0),
}))

function formatCount(value: number): string {
  return new Intl.NumberFormat('ru-RU').format(value)
}

function showcasePhotoUrl(key?: string): string | undefined {
  if (!key) return undefined
  if (/^https?:\/\//.test(key)) return key
  return `/api/v1/public/photo?key=${encodeURIComponent(key)}`
}

async function loadShowcase() {
  try {
    const response = await request<{
      data: { name: string; slug: string; photo?: string; series_count: number; products_count: number }[]
    }>('/api/v1/public/brands')
    showcaseBrands.value = response.data.map((brand) => ({
      name: brand.name,
      slug: brand.slug,
      photo: brand.photo,
      seriesCount: brand.series_count,
      productsCount: brand.products_count,
    }))
    catalogDate.value = new Intl.DateTimeFormat('ru-RU', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
    }).format(new Date())
  } catch {
    showcaseFailed.value = true
  } finally {
    showcaseLoading.value = false
  }
}

function openSearch() {
  if (import.meta.client) window.dispatchEvent(new CustomEvent('price:open-search'))
}

onMounted(() => {
  void loadShowcase()
})
</script>

<template>
  <div class="landing-trade">
    <section class="hero section-wrap">
      <div class="hero-copy">
        <div class="eyebrow"><span class="eyebrow-line" /> Светотехника и электромонтаж</div>
        <h1>Цены, по которым<br><em>закупают.</em></h1>
        <p class="hero-lead">
          Price Web — рабочее место оптового клиента. Один каталог, открытая номенклатура и понятный заказ без десяти писем менеджеру.
        </p>
        <div class="hero-actions">
          <NuxtLink :to="primaryCatalogPath" class="button button--primary">Открыть каталог <span>→</span></NuxtLink>
          <a class="text-link" href="#company">Как работаем <span>↓</span></a>
        </div>
        <div class="hero-note">
          <span class="pulse" />
          <template v-if="showcaseLoading">Загружаем актуальный состав каталога</template>
          <template v-else-if="catalogStats.products">{{ formatCount(catalogStats.products) }} позиций в открытом каталоге</template>
          <template v-else>Каталог временно недоступен</template>
        </div>
      </div>

      <div class="hero-panel" aria-label="Состояние публичного каталога">
        <div class="panel-topline">
          <span>Товарная матрица / {{ catalogDate || 'каталог' }}</span>
          <span class="panel-status">● PUBLIC</span>
        </div>
        <div class="panel-heading">
          <div>
            <span class="panel-kicker">Открытая номенклатура</span>
            <strong>Свет, электрика,<br>компоненты</strong>
          </div>
          <div class="panel-stamp">PW<br><small>24/7</small></div>
        </div>
        <div class="panel-chart" aria-hidden="true">
          <div class="chart-label chart-label--a">{{ formatCount(catalogStats.products) }}</div>
          <div class="chart-label chart-label--b">{{ formatCount(catalogStats.series) }}</div>
          <div class="chart-bars">
            <i v-for="(height, index) in ['38%', '56%', '49%', '74%', '67%', '88%', '82%', '100%', '94%', '100%', '92%', '100%']" :key="index" :style="{ '--h': height }" />
          </div>
          <div class="chart-grid" />
        </div>
        <div v-if="showcaseLoading" class="panel-products" aria-label="Загрузка каталога" aria-busy="true">
          <div v-for="index in 3" :key="index" class="mini-product mini-product--loading">
            <span class="catalog-skeleton" /><span class="catalog-skeleton catalog-skeleton--wide" />
          </div>
        </div>
        <div v-else-if="heroBrands.length" class="panel-products">
          <div v-for="brand in heroBrands" :key="brand.slug" class="mini-product">
            <span class="product-swatch">
              <img v-if="brand.photo" :src="showcasePhotoUrl(brand.photo)" alt="" loading="eager">
            </span>
            <div>
              <b>{{ brand.name }}</b>
              <small>{{ brand.seriesCount }} серий · {{ formatCount(brand.productsCount) }} поз.</small>
            </div>
            <strong>→</strong>
          </div>
        </div>
        <p v-else class="panel-empty">Каталог временно недоступен.</p>
        <div class="panel-footer"><span>Публичный API v1</span><span>↗ {{ catalogStats.brands }} брендов</span></div>
      </div>
    </section>

    <section class="signal-bar" aria-label="Возможности портала">
      <div class="signal-item"><span class="signal-icon">01</span><b>Открытый каталог</b><small>Бренды и состав видны до входа</small></div>
      <div class="signal-item"><span class="signal-icon">02</span><b>Персональные цены</b><small>По договору клиента</small></div>
      <div class="signal-item"><span class="signal-icon">03</span><b>Заявка онлайн</b><small>Без ручного переноса</small></div>
      <div class="signal-item"><span class="signal-icon">04</span><b>Статусы в кабинете</b><small>Контроль текущей заявки</small></div>
    </section>

    <section class="catalog-section section-wrap" aria-labelledby="catalog-heading">
      <div class="section-heading">
        <div>
          <div class="eyebrow"><span class="eyebrow-line" /> Каталог без лишних шагов</div>
          <h2 id="catalog-heading">Всё, что нужно<br><em>для закупки.</em></h2>
        </div>
        <div class="section-aside">
          <p>Откройте бренд, затем серию и изучите номенклатуру для следующей закупки.</p>
          <NuxtLink to="/brands" class="text-link">Смотреть все бренды <span>→</span></NuxtLink>
        </div>
      </div>

      <div class="catalog-toolbar">
        <div class="category-tabs" aria-label="Раздел каталога">
          <span class="category-tab is-active">Все бренды <b>{{ formatCount(catalogStats.brands) }}</b></span>
        </div>
        <button type="button" class="catalog-search" aria-label="Открыть поиск по порталу" @click="openSearch">
          <span>⌕</span><span>Поиск по каталогу</span>
        </button>
      </div>

      <div class="product-table">
        <div class="product-row product-row--head"><span>Бренд</span><span>Код / серии</span><span>Позиции</span><span>Доступ</span><span /></div>
        <template v-if="showcaseLoading">
          <div v-for="index in 4" :key="index" class="product-row product-row--loading" aria-label="Загрузка каталога" aria-busy="true">
            <span class="catalog-skeleton" /><span class="catalog-skeleton catalog-skeleton--wide" /><span class="catalog-skeleton" /><span class="catalog-skeleton" /><span />
          </div>
        </template>
        <template v-else>
          <NuxtLink
            v-for="brand in catalogRows"
            :key="brand.slug"
            :to="`/brands/${encodeURIComponent(brand.slug)}`"
            class="product-row product-row--link"
            :aria-label="`Открыть бренд ${brand.name}`"
          >
            <div class="product-name">
              <span class="product-swatch product-swatch--large">
                <img v-if="brand.photo" :src="showcasePhotoUrl(brand.photo)" alt="" loading="lazy">
              </span>
              <div><b>{{ brand.name }}</b><small>Открыть номенклатуру</small></div>
            </div>
            <div class="product-id"><b>{{ brand.slug }}</b><small>{{ brand.seriesCount }} серий</small></div>
            <div class="product-price"><b>{{ formatCount(brand.productsCount) }}</b><small>позиций</small></div>
            <div class="stock stock--in"><i /> Публично</div>
            <span class="add-button" aria-hidden="true">→</span>
          </NuxtLink>
        </template>
      </div>

      <p v-if="!showcaseLoading && !catalogRows.length" class="catalog-message">
        {{ showcaseFailed ? 'Каталог временно недоступен.' : 'В каталоге пока нет брендов.' }}
      </p>

      <div class="catalog-bottom">
        <span>Показано {{ catalogRows.length }} из {{ formatCount(catalogStats.brands) }} брендов</span>
        <NuxtLink to="/brands" class="button button--outline">Открыть полный каталог <span>↗</span></NuxtLink>
      </div>
    </section>

    <LandingTestimonials />

    <section id="brands" class="brands-section section-wrap" aria-labelledby="brands-heading">
      <div class="brand-wall">
        <div class="brand-wall__intro">
          <span class="eyebrow"><span class="eyebrow-line" /> Реальные бренды</span>
          <h2 id="brands-heading">Каталог, который<br><em>можно проверить.</em></h2>
        </div>
        <div v-if="showcaseLoading" class="brand-list" aria-label="Загрузка брендов" aria-busy="true">
          <div v-for="index in 6" :key="index" class="brand-list__loading"><span class="catalog-skeleton catalog-skeleton--wide" /></div>
        </div>
        <div v-else-if="wallBrands.length" class="brand-list">
          <template v-for="brand in wallBrands" :key="brand.slug">
            <NuxtLink :to="`/brands/${encodeURIComponent(brand.slug)}`" class="brand-list__item">
              <img v-if="brand.photo" :src="showcasePhotoUrl(brand.photo)" :alt="brand.name" loading="lazy">
              <span v-else>{{ brand.name }}</span>
              <small>{{ brand.seriesCount }} серий · {{ formatCount(brand.productsCount) }} поз.</small>
            </NuxtLink>
          </template>
        </div>
        <p v-else class="catalog-message">Каталог временно недоступен.</p>
      </div>
    </section>

    <section id="delivery" class="delivery-section" aria-labelledby="delivery-heading">
      <div class="section-wrap delivery-grid">
        <div class="delivery-title">
          <div class="eyebrow eyebrow--light"><span class="eyebrow-line" /> От заявки до заказа</div>
          <h2 id="delivery-heading">Один маршрут.<br><em>Без потери контекста.</em></h2>
        </div>
        <div class="delivery-steps">
          <article class="delivery-step">
            <span>01</span><div><h3>Оставляете заявку</h3><p>Передаёте менеджеру компанию, контакт и комментарий через публичную форму.</p></div><b>Онлайн</b>
          </article>
          <article class="delivery-step">
            <span>02</span><div><h3>Получаете доступ</h3><p>Менеджер создаёт учётную запись и настраивает коммерческие условия.</p></div><b>Менеджер</b>
          </article>
          <article class="delivery-step">
            <span>03</span><div><h3>Работаете с заказом</h3><p>Каталог, корзина, заявка и её актуальный статус собраны в кабинете.</p></div><b>Кабинет</b>
          </article>
        </div>
      </div>
    </section>

    <section id="company" class="company-section section-wrap" aria-labelledby="company-heading">
      <div class="company-quote">
        <span class="quote-mark" aria-hidden="true">“</span>
        <blockquote id="company-heading">В прайсе остаются позиции, условия и следующий шаг. Всё остальное — между вами и менеджером.</blockquote>
        <div class="quote-author">
          <span class="avatar">PW</span>
          <div><b>{{ COMPANY_NAME }}</b><small>оптовый контур закупок</small></div>
        </div>
      </div>
      <div class="company-facts" aria-label="Показатели каталога">
        <div><strong>{{ formatCount(catalogStats.brands) }}</strong><span>брендов<br>в публичном каталоге</span></div>
        <div><strong>{{ formatCount(catalogStats.series) }}</strong><span>серий<br>для выбора</span></div>
        <div><strong>{{ formatCount(catalogStats.products) }}</strong><span>позиций<br>в номенклатуре</span></div>
        <div><strong>24/7</strong><span>доступ<br>из кабинета</span></div>
      </div>

      <div class="faq-block" aria-labelledby="faq-heading">
        <div>
          <span class="eyebrow"><span class="eyebrow-line" /> До начала работы</span>
          <h3 id="faq-heading">Частые вопросы</h3>
        </div>
        <div class="faq-list">
          <details v-for="item in FAQ_ITEMS" :key="item.question" class="faq-item">
            <summary>{{ item.question }} <span>＋</span></summary>
            <p>{{ item.answer }}</p>
          </details>
        </div>
      </div>
    </section>

    <section id="lead" class="final-cta section-wrap" aria-labelledby="final-cta-heading">
      <div class="final-cta__content">
        <span class="eyebrow"><span class="eyebrow-line" /> Начните с каталога</span>
        <h2 id="final-cta-heading">Покупайте быстрее.<br><em>Считайте точнее.</em></h2>
        <p>Откройте номенклатуру без регистрации или оставьте заявку менеджеру на персональные условия.</p>
        <div class="hero-actions">
          <NuxtLink :to="accountPath" class="button button--primary">{{ isAuthenticated ? 'Перейти в кабинет' : 'Войти в кабинет' }} <span>→</span></NuxtLink>
          <NuxtLink to="/brands" class="text-link">Открыть каталог <span>↗</span></NuxtLink>
        </div>
      </div>
      <div class="final-cta__side">
        <button type="button" class="final-card" @click="showContactModal = true">
          <span>Заявка на доступ</span>
          <b>Обсудить условия</b>
          <small>Для компании и ИП</small>
          <i aria-hidden="true">→</i>
        </button>
        <div class="final-stamp" aria-hidden="true">PRICE<br>WEB<br><small>trade portal</small></div>
      </div>
    </section>

    <ManagerContactModal :show="showContactModal" @close="showContactModal = false" />
  </div>
</template>
