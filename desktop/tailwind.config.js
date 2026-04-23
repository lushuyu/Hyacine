/** @type {import('tailwindcss').Config} */
export default {
  content: ['./src/**/*.{html,js,svelte,ts}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // Hyacine aurora palette — design tokens from brand.jsx
        hy: {
          pink: '#F4B6C9',
          pinkDeep: '#E89BB4',
          lavender: '#C9B8F0',
          lavenderDeep: '#A890E0',
          sky: '#A8D5F5',
          skyDeep: '#7FB8E8',
          mint: '#BDE3C8',
          gold: '#E8C77A',
          goldDeep: '#C9A856',
          cream: '#FAF5E8',
          creamWarm: '#F3EBD7',
          ink: '#2A1F3D',
          inkDeep: '#1A1028',
          plum: '#3D2A5A',
          muted: '#8B7BA3',
          line: '#EFEAF5',
          chrome: '#FBFAFD'
        },
        // `brand` kept for backward-compat with existing class usage
        // (bg-brand-500, ring-brand-400, accent-brand-500, text-brand-500).
        // Remapped to Hyacine lavender so every existing reference picks up
        // the new aesthetic without touching every call site.
        brand: {
          50: '#FDFAFF',
          100: '#F5F0FC',
          200: '#EFEAF5',
          300: '#DFD2F4',
          400: '#C9B8F0',
          500: '#A890E0',
          600: '#8E73D0',
          700: '#6E55B0',
          800: '#4B3C80',
          900: '#3D2A5A'
        }
      },
      fontFamily: {
        sans: [
          'Inter',
          '"Noto Sans SC"',
          '-apple-system',
          'BlinkMacSystemFont',
          'Segoe UI',
          'Roboto',
          'sans-serif'
        ],
        serif: [
          '"Noto Serif SC"',
          'ui-serif',
          'Georgia',
          'Cambria',
          '"Times New Roman"',
          'serif'
        ],
        mono: ['"JetBrains Mono"', 'SF Mono', 'Menlo', 'monospace']
      },
      backgroundImage: {
        'aurora-light': `
          radial-gradient(ellipse 80% 60% at 20% 20%, rgba(244,182,201,.55) 0%, transparent 55%),
          radial-gradient(ellipse 70% 55% at 85% 25%, rgba(201,184,240,.65) 0%, transparent 55%),
          radial-gradient(ellipse 90% 65% at 70% 85%, rgba(168,213,245,.55) 0%, transparent 60%),
          radial-gradient(ellipse 60% 50% at 15% 85%, rgba(189,227,200,.50) 0%, transparent 55%),
          linear-gradient(160deg, #FFF4F8 0%, #F0E8FB 50%, #E6F2FB 100%)
        `,
        'aurora-dark': `
          radial-gradient(ellipse 80% 60% at 20% 20%, rgba(244,182,201,.22) 0%, transparent 55%),
          radial-gradient(ellipse 70% 55% at 85% 25%, rgba(201,184,240,.28) 0%, transparent 55%),
          radial-gradient(ellipse 90% 65% at 70% 85%, rgba(168,213,245,.22) 0%, transparent 60%),
          linear-gradient(160deg, #2A1F3D 0%, #3D2A5A 50%, #1A1028 100%)
        `,
        'hy-gradient': 'linear-gradient(135deg, #A890E0 0%, #E89BB4 100%)',
        'hy-logo': 'linear-gradient(135deg, #F4B6C9 0%, #C9B8F0 50%, #A8D5F5 100%)'
      },
      boxShadow: {
        aurora: '0 30px 80px rgba(61, 42, 90, 0.18), 0 8px 24px rgba(61, 42, 90, 0.08)',
        pansy: '0 4px 14px rgba(168, 144, 224, 0.45)',
        'pansy-sm': '0 4px 12px rgba(201, 184, 240, 0.35)',
        'card-hy': '0 1px 2px rgba(61, 42, 90, 0.04), 0 4px 20px rgba(61, 42, 90, 0.05)'
      },
      borderRadius: {
        xl: '0.875rem',
        '2xl': '1.125rem'
      },
      animation: {
        'fade-in': 'fadeIn 420ms cubic-bezier(0.16, 1, 0.3, 1)',
        'slide-up': 'slideUp 500ms cubic-bezier(0.16, 1, 0.3, 1)',
        'pulse-ring': 'pulseRing 1800ms cubic-bezier(0.455, 0.03, 0.515, 0.955) infinite',
        'aurora-drift': 'auroraDrift 18s ease-in-out infinite',
        'pansy-spin': 'pansySpin 22s linear infinite'
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0', transform: 'translateY(8px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' }
        },
        slideUp: {
          '0%': { opacity: '0', transform: 'translateY(24px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' }
        },
        pulseRing: {
          '0%': { transform: 'scale(0.8)', opacity: '0.7' },
          '80%, 100%': { transform: 'scale(2.2)', opacity: '0' }
        },
        auroraDrift: {
          '0%, 100%': { transform: 'translate3d(0,0,0) scale(1)' },
          '50%': { transform: 'translate3d(1%, -1.2%, 0) scale(1.03)' }
        },
        pansySpin: {
          '0%': { transform: 'rotate(0deg)' },
          '100%': { transform: 'rotate(360deg)' }
        }
      }
    }
  },
  plugins: []
};
