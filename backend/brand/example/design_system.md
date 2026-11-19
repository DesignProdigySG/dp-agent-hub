# Example Co Design System

A small sample. Replace it with your own; keep the "Colour tokens" heading so the hub can
find your palette.

## 1. Colour tokens

| Token | Hex | Use |
|---|---|---|
| ink-900 | #111827 | Body text, dark backgrounds |
| ink-500 | #6B7280 | Secondary text |
| paper | #FFFFFF | Page background |
| mist | #F3F4F6 | Panels |
| brand-600 | #2563EB | Primary buttons, links |
| brand-50 | #EFF6FF | Highlights |

## 2. Tailwind config

Landing pages load the Tailwind Play CDN and this config:

<script>
tailwind.config = {
  theme: {
    extend: {
      colors: {
        ink: { 900: '#111827', 500: '#6B7280' },
        brand: { 600: '#2563EB', 50: '#EFF6FF' },
        mist: '#F3F4F6',
      },
      fontFamily: { sans: ['Inter', 'system-ui', 'sans-serif'] },
    },
  },
}
</script>

## 3. Email

- 600 px wide, tables, inline styles only.
- Body text #111827 on #FFFFFF; buttons #2563EB with white text.
- Footer: the company address, a privacy link and `{{system.unsubscribeLink}}`.
