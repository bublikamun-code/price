import type { Config } from 'tailwindcss'

const token = (name: string) => `rgb(var(--color-${name}) / <alpha-value>)`

export default <Partial<Config>>{
  content: [
    './components/**/*.{vue,js,ts}',
    './layouts/**/*.vue',
    './pages/**/*.vue',
    './composables/**/*.{js,ts}',
    './app.vue',
    './error.vue',
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        background: token('background'),
        canvas: token('background'),
        surface: token('surface'),
        'surface-2': token('surface-2'),
        'surface-raised': token('surface-raised'),
        service: {
          DEFAULT: token('service'),
          2: token('service-2'),
          ink: token('service-ink'),
          muted: token('service-muted'),
          border: token('service-border'),
        },
        text: token('ink'),
        ink: {
          DEFAULT: token('ink'),
          muted: token('ink-muted'),
          faint: token('ink-muted'),
          'on-service': token('ink-on-service'),
        },
        'text-inverse': token('ink-on-service'),
        border: token('border'),
        'border-strong': token('border-strong'),
        action: {
          DEFAULT: token('action'),
          hover: token('action-hover'),
          soft: token('action-soft'),
          on: token('action-on'),
        },
        primary: {
          DEFAULT: token('action'),
          hover: token('action-hover'),
          soft: token('info-soft'),
        },
        accent: {
          DEFAULT: token('action'),
          hover: token('action-hover'),
          soft: token('danger-soft'),
        },
        secondary: {
          DEFAULT: token('ink'),
          soft: token('surface-2'),
        },
        success: {
          DEFAULT: token('success'),
          soft: token('success-soft'),
          text: token('success-text'),
        },
        warning: {
          DEFAULT: token('warning'),
          soft: token('warning-soft'),
          text: token('warning-text'),
        },
        danger: {
          DEFAULT: token('danger'),
          on: token('danger-on'),
          soft: token('danger-soft'),
          text: token('danger-text'),
        },
        destructive: {
          DEFAULT: token('danger'),
          soft: token('danger-soft'),
        },
        info: {
          DEFAULT: token('info'),
          soft: token('info-soft'),
        },
        focus: token('focus'),
        glass: token('surface'),
        'glass-border': token('border'),
      },
      fontFamily: {
        sans: ['var(--font-sans)'],
        display: ['var(--font-display)'],
        mono: ['var(--font-mono)'],
      },
      fontSize: {
        xs: ['0.75rem', { lineHeight: '1.4167' }],
        sm: ['0.875rem', { lineHeight: '1.4286' }],
        base: ['1rem', { lineHeight: '1.5' }],
        lg: ['1.125rem', { lineHeight: '1.4375' }],
        xl: ['1.5rem', { lineHeight: '1.3333' }],
        '2xl': ['1.5rem', { lineHeight: '1.3333' }],
        '3xl': ['1.875rem', { lineHeight: '1.35' }],
      },
      fontWeight: {
        normal: '400',
        medium: '450',
        semibold: '600',
        bold: '700',
        extrabold: '800',
      },
      borderRadius: {
        none: '0',
        control: 'var(--radius-control)',
        surface: 'var(--radius-surface)',
        dialog: 'var(--radius-dialog)',
        card: 'var(--radius-surface)',
        pill: 'var(--radius-pill)',
      },
      boxShadow: {
        overlay: 'var(--shadow-overlay)',
        sticky: 'var(--shadow-sticky)',
        card: 'none',
        'card-hover': 'none',
      },
      transitionTimingFunction: {
        trade: 'cubic-bezier(0.2, 0, 0, 1)',
      },
      spacing: {
        18: '4.5rem',
      },
    },
  },
  plugins: [],
}
