/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'monospace'],
      },
      colors: {
        canvas: '#0b0c0e',
        sidebar: '#111217',
        panel: '#111217',
        card: '#111217',
        'card-hover': '#202226',
        line: '#2a2d30',
        'line-subtle': 'rgba(42, 45, 48, 0.72)',
        ink: '#d8d9da',
        muted: '#a7a9ab',
        subtle: '#7b7d80',
        'accent-green': '#73bf69',
        'accent-blue': '#5794f2',
        'accent-orange': '#ff9830',
        'accent-red': '#f2495c',
        'accent-yellow': '#f2cc0c',
        'accent-purple': '#b877d9',
        lime: '#73bf69',
        violet: '#b877d9',
        brand: {
          50: '#f5f3ff',
          100: '#ede9fe',
          200: '#ddd6fe',
          300: '#c4b5fd',
          400: '#a78bfa',
          500: '#8b5cf6',
          600: '#7c3aed',
          700: '#6d28d9',
        },
      },
      boxShadow: {
        subtle: '0 0 0 1px rgba(42, 45, 48, 0.9)',
        panel: '0 0 0 1px rgba(42, 45, 48, 0.9)',
      },
    },
  },
  plugins: [],
}
