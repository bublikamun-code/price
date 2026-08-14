import type { Config } from 'tailwindcss'

// Дизайн-система — см. ARCHITECTURE_PLAN.md §3
// Принципы: плоский, воздушный, минимализм, мягкие цвета, плитка (card-based).
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
        // Поверхности
        canvas: '#F7F9FC', // фон
        surface: '#FFFFFF', // карточки
        'surface-2': '#FBFCFE', // приподнятая карточка
        border: '#E6EAF0',
        // Акценты (мягкие)
        primary: {
          DEFAULT: '#5B8DEF',
          hover: '#4A7DD8',
          soft: '#EAF1FD',
        },
        secondary: {
          DEFAULT: '#8B7EE6',
          soft: '#F0ECFB',
        },
        // Семантика (приглушённые)
        success: { DEFAULT: '#4CAF85', soft: '#E7F6EF' },
        warning: { DEFAULT: '#F2B33D', soft: '#FDF1DC' },
        danger: { DEFAULT: '#E26D6D', soft: '#FBE7E7' },
        // Текст
        ink: {
          DEFAULT: '#1F2937',
          muted: '#6B7280',
          faint: '#9CA3AF',
        },
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        display: ['Manrope', 'Inter', 'sans-serif'],
      },
      fontSize: {
        // воздушная типографика
        xs: ['0.75rem', { lineHeight: '1.5' }],
        sm: ['0.875rem', { lineHeight: '1.5' }],
        base: ['1rem', { lineHeight: '1.6' }],
        lg: ['1.125rem', { lineHeight: '1.6' }],
        xl: ['1.5rem', { lineHeight: '1.4' }],
        '2xl': ['1.5rem', { lineHeight: '1.3' }],
        '3xl': ['2rem', { lineHeight: '1.2' }],
      },
      borderRadius: {
        card: '16px',
        pill: '999px',
      },
      boxShadow: {
        // мягкие тени для «воздушности»
        card: '0 1px 2px rgba(43,57,83,0.04), 0 4px 20px rgba(43,57,83,0.06)',
        'card-hover': '0 2px 4px rgba(43,57,83,0.06), 0 12px 32px rgba(43,57,83,0.10)',
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
