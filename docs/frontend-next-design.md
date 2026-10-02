# TraceScope UI design guide (`frontend-next`)

This guide is for an agent who adds pages to `frontend-next` or restyles another app (for example `frontend/`) to match it. The code that defines the style is:

- `src/styles/tokens.css`: every color, shadow and theme value.
- `src/styles/base.css`: every class named below.
- `src/components/*`: the React primitives.

If this guide and those files disagree, the files are correct. Update this guide when you change them.

---

## 1. Principles

1. **Quiet surfaces, one accent.** Pages are white and grey. Purple (`--accent`) marks only the active nav item, icon boxes, thumbnails, the primary chart series and selection. Do not add other brand colors.
2. **Light mode first.** Design and check in light mode. Dark mode is its own token set, not an inversion. Only change dark mode by editing tokens.
3. **Use tokens, never literal colors.** Components use `var(--…)` roles only. The one exception is `#fff` text on an accent fill.
4. **Every card has a double frame.** A grey outer `.card` with a 3px gutter holds one or more white `.inner` panels. Never put content directly in `.card`. Never nest cards.
5. **Color is never the only signal.** States always carry a text label. The expected or reference series is dashed. Change pills show an arrow for direction and color for tone.
6. **Direction and judgement are separate.** An increase is not automatically good. TPS changes use the `neutral` tone. Latency or errors rising use `bad`. Only use `good` when the metric really improved.
7. **Show real data only.** Show completed buckets only. Never invent values. Missing data shows `—` or a `StateBox` message.

---

## 2. Tokens (`tokens.css`)

| Role | Light | Dark | Use |
|---|---|---|---|
| `--page` | `#f7f7f8` | `#0c0c0e` | Body behind the app frame |
| `--bg` | `#fff` | `#131316` | App frame, sidebar, topbar, buttons |
| `--surface` | `#fff` | `#18181b` | `.inner` panels, tooltip |
| `--surface-2` | `#fafafa` | `#1e1e22` | `.card` frame, hover, pressed segment, bar track |
| `--border` | `#e8e8ec` | `#2a2a30` | Panel and row dividers |
| `--border-strong` | `#dcdce2` | `#36363d` | Controls: buttons, segments, selects, search, icon box |
| `--text` | `#18181b` | `#f4f4f5` | Primary text and values |
| `--muted` | `#71717a` | `#a1a1aa` | Labels, axis ticks, secondary text |
| `--faint` | `#a1a1aa` | `#71717a` | Placeholders and icons in inputs |
| `--accent` | `#6d4ae8` | `#8f74f2` | Primary series, active and selected states, icons |
| `--accent-soft` | `#efeafd` | `#2a2347` | Selected table row, thumbnail background |
| `--accent-2` | `#f5b13d` | `#e9a530` | Second chart series only (expected or reference) |
| `--up` / `--up-bg` / `--up-bd` | green | green | `Pill tone="good"` |
| `--down` / `--down-bg` / `--down-bd` | red | red | `Pill tone="bad"`, error `StateBox` |
| `--flat` / `--flat-bg` / `--flat-bd` | grey | grey | `Pill tone="neutral"` |
| `--state-good` / `-learning` / `-new` / `-bad` | | | Relationship state dots and the `.flag` text |
| `--shadow` / `--shadow-pop` | | | Card shadow (none in dark) / tooltip and popover |

To add a color, define a role in **both** theme blocks. Name it by role (`--warn`), not by hue (`--orange`).

### Theme mechanics

- The theme lives in `<html data-theme="light|dark">`. It is saved in `localStorage["ts-theme"]`.
- An inline script in `index.html` applies the saved theme before first paint. Keep it.
- `ThemeProvider` / `useTheme()` (`src/theme/theme.tsx`) is the only place that writes the theme. The topbar `ThemeSwitch` is the only control for it.

---

## 3. Typography

The font is Inter (Google Fonts, weights 400/500/600/700), falling back to the system stack. The base size is 14px with a line height of 1.4.

| Use | Size / weight | Class |
|---|---|---|
| Card label (uppercase, muted) | 11.5 / 500 | `.label` |
| Stat value | 20 / 600, tracking −0.01em | `.value` |
| Header value | 22 / 600 | `.value.lg` |
| Unit after a value | 13 / 500 muted | `.value .unit` |
| Entity title in a header | 19 / 600 | `.title-lg` |
| Body and list rows | 13 / 500 | |
| Table | 12.5 | `table` |
| Pill, tooltip, ticks | 11–11.5 | |

- Put `.num` (tabular numbers) on every number that can change.
- Do not use headings larger than 22px. Pages have no hero titles.

---

## 4. Spacing, radius, size

- **Gaps:** 20px between page sections and between grid cards (14px below 760px). 3px between `.inner` panels inside a card.
- **Padding:** `.inner` content uses 14px (`.head`, `.body`). Toolbars and filters use 10px × 14px. Tables use 10/9px × 12px.
- **Radius:** 12px for `.card`, 9px for `.inner` and `.mini`, 8px for controls, tooltip and icon box, 6px for thumbnails, 999px for pills.
- **Icons:** 18px with a 1.8 stroke (`svg.i`), 14–15px inside small controls. Only use `<Icon name=…/>`. Add new glyphs to the `PATHS` map in `Icon.tsx` (24-unit grid, stroke only).

---

## 5. Layout

```
.app (grid 240px | 1fr, max-width 1440, centered, left/right border)
├── <Sidebar active="…"/>   sticky 100vh: brand · search(⌘K) · MAIN MENU · INVESTIGATE · bottom(Settings, Help)
└── <main>
    ├── .topbar  sticky: left = range .seg, right = .actions (refresh .btn.icon, ThemeSwitch)
    └── .content  grid, gap 20, padding 20
        ├── .stats  4 StatCards
        ├── .row2   main card 2.05fr | side card 1fr
        └── .row3   side card 1fr | main card 2.05fr
```

Breakpoints:

- **≤1100px:** `.stats` has 2 columns; `.row2` and `.row3` stack.
- **≤760px:** the sidebar is hidden; `.stats` has 1 column; padding is 14.

A mobile nav does not exist yet. If you add one, use a topbar menu button that opens the same `Sidebar` as an overlay.

Every new page uses the same shell. Put its sections in `.content` using `.stats`, `.row2` and `.row3`, or a single full-width `Card`. Keep the wide panel at **2.05fr** and the narrow one at **1fr**. Alternate sides between rows the way the dashboard does.

Grid children need `min-width: 0` (cards already have it). Text that can be long must truncate with an ellipsis or use `overflow-wrap: anywhere`. The page must never scroll sideways. Wide tables scroll inside `.table-scroll`.

---

## 6. Components and recipes

### Card

```tsx
<Card>
  <CardHead label="Throughput" value={fmtTps(v)} pill={<Pill dir="up" tone="neutral">4.2%</Pill>} icon="pulse" />
  <Inner className="filters"><ChartLegend series={S} /><Select …/></Inner>
  <Inner className="grow chart-wrap"><LineChart … /></Inner>
</Card>
```

- **Header:** first panel. Use `CardHead` with an uppercase `label`, then either a `value` (with an optional `pill`) or a `title`. The right side holds an `icon` box or an `action` (a button or select).
- **Middle panels:** `Inner` with `filters` or `toolbar` for controls, or `body` for text, mini stats and lists.
- **Main panel:** `Inner className="grow"` so cards in the same row end at the same height.
- **Footer:** a plain `div.stat-foot` sits outside any `Inner`, on the grey frame. Only stat cards use it.

### StatCard

```tsx
<StatCard label="P95 latency" value={fmtMs(p95)} unit="ms"
  pill={<Pill dir="up" tone="bad">12%</Pill>} icon="clock"
  foot={<><b>1.27</b>expected now</>} href="#/…" />
```

Always show four stat cards in a row. The value is current. The pill compares with an earlier period. The foot gives context: a bold number followed by a muted phrase.

### Pill

`dir` is `"up"`, `"down"` or omitted (text only). `tone` is `"good"`, `"bad"` or `"neutral"`. Use `changePill(cur, ref, higherIsBad?)` in `App.tsx` as the reference. Changes below 0.5% are `neutral` with no arrow.

### Controls

| Need | Use |
|---|---|
| Two to five exclusive options (range, tabs, column) | `.seg` with `<button aria-pressed>`; `.seg.sm` inside cards |
| Long option list (Service) | `<Select label="…">` (native select styled as a button) |
| Action | `.btn`; `.btn.icon` (icon only, needs `aria-label`); `.btn.sm`; `.btn.primary` for at most one per view |
| Search in a card | `.toolbar .search` with an icon and input; search runs on the server where the API supports `q_*` |

### Ranked list (`.rank`)

Each row is `.item`, containing a name `p` (truncated) and a muted `small` meta line, then `.bar > i` with `width: share%`. A bold value sits on the right. Show at most 5–8 rows and link to the full list.

### Mini stats (`.mini`)

Two cells side by side, each with a muted `small` label and a 21px `strong` value. Use them for observed versus expected and similar pairs.

### Table

```tsx
<div className="table-scroll"><table>
  <thead><tr><th>Name</th><th>State</th><th className="r">Observed TPS</th>…</tr></thead>
  <tbody><tr className={sel ? "is-selected" : ""} tabIndex={0} onClick=… onKeyDown=Enter/Space>…</tr></tbody>
</table></div>
```

- **Numeric columns:** right-aligned (`.r`) and use `.num`.
- **Name cell:** `.name-cell` with a `.thumb` icon and a truncated name.
- **State cell:** `.state` with a `.state-dot` colored by `STATE_META` plus its text label. Unusual rows add a `.flag`.
- **Clickable rows:** must also be keyboard accessible. Selection uses `is-selected` (`--accent-soft`).

### Side list (`.side-list` / `.side-row`)

Use an uppercase `h4` heading and dashed-divider rows with a name on the left and a value on the right. These are the neighbour lists in a selection card.

### States

| Situation | Show |
|---|---|
| Loading | `<StateBox>Loading…</StateBox>` |
| Empty | `<StateBox>No … in this range</StateBox>`; say why, not just "No data" |
| Error | `<StateBox error>` with the message |

The card keeps its size while loading. Do not show spinners over charts.

---

## 7. Charts (`LineChart.tsx`)

Use this component for every time series. Do not add a chart library.

- **Primary series:** `color: "var(--accent)"`, `area: true` (gradient fill). Only one series may have an area.
- **Reference series:** `color: "var(--accent-2)"`, `dashed: true`.
- **Third series:** needs a new token and a second channel (dash or marker) as well as color. Show at most 3 series.
- **Y axis:** one axis, starting at zero, with round ticks (`niceTicks`). Never use two y-axes. Show a second unit in its own chart.
- **Shape:** smooth midpoint curves, dashed vertical guides, no dots until hover. On hover, a band, dots and a tooltip appear; the tooltip flips sides at the edge.
- **Gaps:** `null` values break the line. Do not interpolate across missing buckets.
- **Height:** 300 in a `.row2` main card. 160–200 for small inline trends.
- **Legend:** always `ChartLegend` in the `filters` panel above the chart. Do not put the legend inside the plot.
- **Labels:** pass `format` (for example `fmtTps`) and `ariaLabel`.

Other chart types (bars, heatmaps) should follow the same rules: tokens only, a muted 11px axis, `--border` grid lines, a `.lc-tip`-style tooltip and zero-based scales.

---

## 8. Content rules

- Use these names: Service, API, User, Caller service, TPS, P95, Expected. API names drop the Service prefix when the Service is already in context (`shortName`).
- Numbers use the helpers in `src/api/format.ts`: `fmtTps`, `fmtInt`, `fmtMs`, `fmtTime`, `fmtAgo`. Do not use raw `toFixed` in components.
- Labels are short nouns ("Current TPS"), not sentences. Explanations go in the stat foot or the `.body p`.
- Relationship states and their labels come from `features/relationship/state.ts`: Established, Learning, New, Deviating, Not seen, Dormant.

---

## 9. Accessibility

- Every focusable element shows the global `:focus-visible` ring. Do not remove it.
- Toggle buttons use `aria-pressed`. Icon-only buttons and selects have `aria-label`.
- Text contrast: `--text` and `--muted` meet AA on `--surface` in both themes. Do not use `--faint` for information.
- Anything you can click also works with Enter and Space.
- Do not add motion beyond hover color changes. `prefers-reduced-motion` already disables transitions.

---

## 10. Adding a page (checklist)

1. Create `src/features/<area>/<Page>.tsx`. Fetch with `useApi(path, query)` (it aborts stale requests) and add types to `src/api/types.ts`.
2. Render inside the existing shell. Set `Sidebar active="<id>"` and reuse the topbar range.
3. Lay out the page as `.stats`, then `.row2` / `.row3`, or as full-width cards. Every card follows header → controls → `Inner.grow` main panel.
4. Use only the primitives and classes listed above. If you need a new pattern, add a class to `base.css` using tokens and document it here.
5. Handle loading, empty and error states in every card.
6. Verify:
   - `npm run build` is clean.
   - Check in Chromium at 1440 light, 1440 dark and 390 light.
   - There are no console errors and no horizontal overflow (`document.documentElement.scrollWidth <= innerWidth`).
   - Hover and keyboard paths work.

---

## 11. Porting this style to another codebase (e.g. `frontend/` with Tailwind)

1. Copy the `tokens.css` blocks into that app's global CSS. Map its theme attribute to `data-theme`, or rename the selectors.
2. In Tailwind, expose the roles: `colors: { page: 'var(--page)', surface: 'var(--surface)', 'surface-2': 'var(--surface-2)', line: 'var(--border)', 'line-strong': 'var(--border-strong)', ink: 'var(--text)', muted: 'var(--muted)', accent: 'var(--accent)', 'accent-soft': 'var(--accent-soft)', 'accent-2': 'var(--accent-2)' }`.
3. Replace hard-coded hex utilities (`text-[#…]`, `bg-[#…]`) with role classes. Do not override them with wildcard selectors.
4. Rebuild these first: panels as the double frame (`rounded-xl border border-line bg-surface-2 p-[3px]` › `rounded-[9px] border border-line bg-surface`), KPI cards as `StatCard`, and segmented controls and pills as in section 6.
5. Restyle charts to section 7: accent area plus a dashed `accent-2` reference, one zero-based axis, no glow, and token colors in Recharts/ECharts options.
6. Change one page at a time, then run that app's build and the same browser checks.

What not to do:

- Gradients anywhere except the chart area fill.
- Glow or neon shadows, glassy blur effects.
- More than one primary button per view.
- Red or green for neutral traffic changes.
- Icons from other sets mixed with `Icon`.
- Fixed pixel widths that cause horizontal scroll.
