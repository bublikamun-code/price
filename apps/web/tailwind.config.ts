import type { Config } from 'tailwindcss'

// Дизайн-система — см. ARCHITECTURE_PLAN.md §3
// Токены — CSS-переменные (assets/css/main.css, :root и .dark).
// Тёмная тема: класс `dark` на <html> (@nuxtjs/color-mode, preference по умолчанию — dark).
// Источник палитры — прод-билд нового дизайна (бэкап чанков § «восстановление дизайна»).
export default <Partial<Config>>{
  content: [
    './components/**/*.{vue,js,ts}',
    './layouts/**/*.vue',
    './pages/**/*.vue',
    './composables/**/*.{js,ts}',
    './app.vue',
    './error.vue',
  ],
  theme: {
    extend: {
      colors: {
        // Поверхности — токены
        canvas: 'rgb(var(--color-canvas) / <alpha-value>)',
        surface: 'rgb(var(--color-surface) / <alpha-value>)',
        'surface-2': 'rgb(var(--color-surface-2) / <alpha-value>)',
        border: 'rgb(var(--color-border) / <alpha-value>)',
        // Акценты
        primary: {
          DEFAULT: 'rgb(var(--color-primary) / <alpha-value>)',
          hover: 'rgb(var(--color-primary-hover) / <alpha-value>)',
          soft: 'rgb(var(--color-primary-soft) / <alpha-value>)',
        },
        secondary: {
          DEFAULT: 'rgb(var(--color-secondary) / <alpha-value>)',
          soft: 'rgb(var(--color-secondary-soft) / <alpha-value>)',
        },
        // Семантика
        destructive: {
          DEFAULT: 'rgb(var(--color-destructive) / <alpha-value>)',
          soft: 'rgb(var(--color-destructive-soft) / <alpha-value>)',
        },
        success: {
          DEFAULT: 'rgb(var(--color-success) / <alpha-value>)',
          soft: 'rgb(var(--color-success-soft) / <alpha-value>)',
          text: 'rgb(var(--color-success-text) / <alpha-value>)',
        },
        warning: {
          DEFAULT: 'rgb(var(--color-warning) / <alpha-value>)',
          soft: 'rgb(var(--color-warning-soft) / <alpha-value>)',
          text: 'rgb(var(--color-warning-text) / <alpha-value>)',
        },
        danger: {
          DEFAULT: 'rgb(var(--color-danger) / <alpha-value>)',
          soft: 'rgb(var(--color-danger-soft) / <alpha-value>)',
          text: 'rgb(var(--color-danger-text) / <alpha-value>)',
        },
        'info-text': 'rgb(var(--color-info-text) / <alpha-value>)',
        // Текст
        ink: {
          DEFAULT: 'rgb(var(--color-ink) / <alpha-value>)',
          muted: 'rgb(var(--color-ink-muted) / <alpha-value>)',
          faint: 'rgb(var(--color-ink-faint) / <alpha-value>)',
        },
      },
      fontFamily: {
        sans: ['Geist', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        display: ['Geist', 'ui-sans-serif', 'system-ui', 'sans-serif'],
      },
      fontSize: {
        xs: ['0.75rem', { lineHeight: '1.5' }],
        sm: ['0.875rem', { lineHeight: '1.5' }],
        base: ['1rem', { lineHeight: '1.6' }],
        lg: ['1.125rem', { lineHeight: '1.6' }],
        xl: ['1.5rem', { lineHeight: '1.4' }],
        '2xl': ['1.5rem', { lineHeight: '1.3' }],
        '3xl': ['2rem', { lineHeight: '1.2' }],
      },
      borderRadius: {
        card: '24px',
        pill: '999px',
      },
      boxShadow: {
        card: '0 0 0 1px hsla(0,0%,9%,.05), 0 1px 3px rgba(0,0,0,.1), 0 1px 2px -1px rgba(0,0,0,.1)',
        'card-hover': '0 0 0 1px hsla(0,0%,9%,.08), 0 2px 6px rgba(0,0,0,.12), 0 2px 4px -2px rgba(0,0,0,.1)',
      },
      transitionTimingFunction: {
        soft: 'cubic-bezier(0.4, 0, 0.2, 1)',
      },
      spacing: {
        18: '4.5rem',
      },
    },
  },
  plugins: [],
}
