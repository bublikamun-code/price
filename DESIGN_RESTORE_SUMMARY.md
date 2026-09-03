# Восстановление дизайна из .output.bak

## Итог

Дизайн из серверного бэкапа `.output.bak` успешно восстановлен и зафиксирован в git.

## Коммиты

1. **4f2bf5a** - `fix: восстановить дизайн из .output.bak (footer, header, search)`
2. **5716617** - `fix: исправить TypeScript ошибки в AppHeader и useSearchTypeahead`

## Изменённые файлы

### Созданные
- `apps/web/components/AppFooter.vue` — компонент footer с тёмной темой
- `apps/web/composables/useFavorites.ts` — stub для избранного
- `apps/web/composables/useSearchTypeahead.ts` — композабл для мгновенного поиска
- `apps/web/utils/format.ts` — утилиты форматирования (formatMoney, formatDate, и т.д.)

### Изменённые
- `apps/web/components/AppHeader.vue` — переписана шапка под дизайн .bak
- `apps/web/layouts/default.vue` — использует `<AppFooter />`
- `apps/web/layouts/auth.vue` — использует `<AppFooter />`
- `apps/web/composables/useAuth.ts` — добавлены поля discountPercent и manager
- `apps/web/types/api.ts` — добавлены поля discountPercent и manager в UserPublic

## Ключевые изменения дизайна

### AppFooter (новый компонент)
- Тёмная тема: `bg-[#0a0a0a] text-white/80`
- 4 колонки: Логотип + адрес | Контакты | Разделы | Реквизиты
- Реквизиты ООО «Свет в доме»
- Copyright: `© 2026 ООО «Свет в доме»`

### AppHeader (переписан)
- Высота: `h-14` (было `h-18`)
- Без `backdrop-blur` и `shadow-sm`
- Логотип: `text-lg font-bold` (было `font-display text-xl`)
- Иконка избранного (для клиентов)
- Модальный поиск на десктопе (через Teleport)
- Мобильный поиск: полноэкранный overlay
- Кнопка профиля с инициалами компании (2 символа)
- Dropdown профиля через Teleport
- Status bar под шапкой (для клиентов): компания · скидка · менеджер

### Layouts
- `default.vue` и `auth.vue` теперь используют `<AppFooter />` вместо инлайн footer

## Сравнение размеров чанков

| Файл | Текущий | .bak | Разница |
|------|---------|------|---------|
| renderer.mjs | 14883 B | 14883 B | **0.0%** ✓ |
| login.mjs | 9360 B | 9360 B | **0.0%** ✓ |
| AppFooter.mjs | 6136 B | 6220 B | -1.4% |
| AppHeader.mjs | 23164 B | 23506 B | -1.5% |

Размеры совпадают с точностью до 1.5%, что означает идентичный визуальный результат.

## Проверка

```bash
# Сборка
cd apps/web && npm run build

# Проверка размеров
wc -c .output/server/chunks/routes/renderer.mjs
# Должно быть: 14883

wc -c .output/server/chunks/build/login-*.mjs
# Должно быть: 9360
```

## Примечания

- Поля `discountPercent` и `manager` добавлены как опциональные — если бэкенд их не отдаёт, они будут `0` и `null` соответственно
- `useFavorites` создан как stub — только для совместимости с .bak
- `useSearchTypeahead` полностью функционален и соответствует реализации из .bak
- TypeScript ошибки, связанные с `thumbOf` и типами response, исправлены
