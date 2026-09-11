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
        canvas: '#12101b',
        panel: '#161424',
        card: '#1a172a',
        'card-hover': '#221e38',
        line: 'rgba(255, 255, 255, 0.14)',
        'line-subtle': 'rgba(255, 255, 255, 0.08)',
        lime: '#10b981',
        violet: '#8b5cf6',
        coral: '#f43f5e',
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
        subtle: '0 1px 2px 0 rgba(0, 0, 0, 0.5), 0 0 0 1px rgba(255, 255, 255, 0.12)',
        panel: '0 8px 30px -4px rgba(0, 0, 0, 0.6), 0 0 0 1px rgba(255, 255, 255, 0.12)',
        glow: '0 0 20px -2px rgba(139, 92, 246, 0.35)',
        'glow-cyan': '0 0 20px -2px rgba(6, 182, 212, 0.4)',
        'glow-violet': '0 0 20px -2px rgba(139, 92, 246, 0.4)',
        'glow-amber': '0 0 20px -2px rgba(245, 158, 11, 0.4)',
        'glow-emerald': '0 0 20px -2px rgba(16, 185, 129, 0.4)',
        'glow-rose': '0 0 20px -2px rgba(244, 63, 94, 0.4)',
      },
    },
  },
  plugins: [],
}
