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
        canvas: '#08090a',
        panel: '#0d0f12',
        card: '#12151a',
        'card-hover': '#171b22',
        line: 'rgba(255, 255, 255, 0.08)',
        'line-subtle': 'rgba(255, 255, 255, 0.04)',
        lime: '#10b981',
        violet: '#7170ff',
        coral: '#f43f5e',
        brand: {
          50: '#eef2ff',
          100: '#e0e7ff',
          400: '#818cf8',
          500: '#6366f1',
          600: '#4f46e5',
        },
      },
      boxShadow: {
        subtle: '0 1px 2px 0 rgba(0, 0, 0, 0.4), 0 0 0 1px rgba(255, 255, 255, 0.06)',
        panel: '0 8px 30px -4px rgba(0, 0, 0, 0.5), 0 0 0 1px rgba(255, 255, 255, 0.07)',
        glow: '0 0 20px -2px rgba(99, 102, 241, 0.25)',
      },
    },
  },
  plugins: [],
}
