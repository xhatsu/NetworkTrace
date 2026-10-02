# Plan: in-place light + dark restyle of `frontend/`

**Audience:** an agent doing the work. Read this file and `frontend-next/DESIGN.md` (the target style) before you start.

**Scope:** colors, surfaces, borders, type, radius, shadows, controls and charts, in **both** themes.

**Out of scope:** page structure, data fetching, routes, i18n, backend.

**Rules:**
- No behaviour changes.
- AGENTS.md rules apply: POSIX sh, never `kubectl`, update `AGENTS.md`/`STATE.md` when state changes, no commit unless asked.

---

## 0. Current state (measured 2026-10-02)

| Fact | Number / location |
|---|---|
| Source | ~20k lines TS/TSX, React 19, Tailwind 3.4, Recharts (14 files), ECharts (`components/ZoomableDashboardChart.tsx`), lucide icons |
| Hard-coded color classes `*-[#hex]` | ~2,330. Mostly `text-` (1,549), `bg-` (369), `border-` (367) |
| `dark:` variants | 584. **Tailwind `darkMode` is not configured, so these follow the OS setting, not the app's theme switch.** That is a live bug, and removing them fixes it. |
| Gray/blue palette classes (`text-slate-500` etc.) | ~604 |
| Hex string literals in TS/TSX (SVG, charts, style props) | ~384 |
| `isLight` / `theme === "light"` branches in TSX | ~42 |
| `src/index.css` | 1,100 lines. About 250 `[class~="bg-[#…]"]` override rules remap dark literals for light mode (lines ~125–690), plus a "ProServe" gradient layer (~997+) |
| Theme sources | `src/theme.ts` (`DARK_THEME`, `LIGHT_THEME`, `getThemeTokens`), `src/chartTheme.ts`, `src/accessEncoding.ts` (`getStateStyle`, `getEntityColor`), CSS vars `--theme-*` and `--canvas` etc. in `index.css`, Tailwind roles in `tailwind.config.js` |
| Theme switch | `App.tsx`: `ThemeContext` / `useTheme`, `localStorage["tracescope-theme"]`, dark by default, sets `html[data-theme]` |
| Files with the most literals | `index.css` 274, `InteractiveTopology.tsx` 221, `UserIntelligence.tsx` 170, `AccessFlow.tsx` 162, `EpisodePrimitives.tsx` 142, `Services.tsx` 121, `Overview.tsx` 121, `Behavior.tsx` 120, `App.tsx` 114, `AgentStats.tsx` 109, `Anomalies.tsx` 107, `AccessExplorer.tsx` 105 |

Re-measure before you start. Another agent may have changed things.

```sh
cd frontend
grep -rhoE "\-\[#[0-9a-fA-F]{3,8}\]" src | wc -l
grep -rhoE "dark:[^ \"'\`]+" src | wc -l
npx tsc --noEmit -p tsconfig.app.json && echo TYPES_OK
```

**End state:**

1. All colors come from one token file.
2. Components use role classes only. No `[#hex]`, no `dark:`, no palette classes except `text-white` on accent fills.
3. The override block in `index.css` is gone.
4. Both themes match `DESIGN.md`.

---

## 1. Target tokens (single source of truth)

Create `src/styles/tokens.css`, imported first in `main.tsx`. Use the **same role names in both themes**. Light is the `:root` default; dark is `:root[data-theme="dark"]`.

### 1.1 Base roles

Copy these from `frontend-next/src/styles/tokens.css`:

| Group | Tokens |
|---|---|
| Surfaces | `--page`, `--bg`, `--surface`, `--surface-2` |
| Borders | `--border`, `--border-strong` |
| Text | `--text`, `--muted`, `--faint` |
| Accents | `--accent`, `--accent-soft`, `--accent-2` |
| Pills | `--up*`, `--down*`, `--flat*` |
| States | `--state-good`, `--state-learning`, `--state-new`, `--state-bad` |
| Shadows | `--shadow`, `--shadow-pop` |

### 1.2 Roles this app also needs

Add these to both theme blocks. The light/dark values below are a starting point; check contrast (§7).

| Role | Light | Dark | Use |
|---|---|---|---|
| `--grid` | `#efeff2` | `#26262b` | Chart grid, table zebra |
| `--hover` | `#f4f4f6` | `#222227` | Row/control hover (= `--surface-2` if equal is fine) |
| `--selected` | `var(--accent-soft)` | `var(--accent-soft)` | Selected row/node |
| `--info` | `#2563eb` | `#6b9cf5` | Informational status, links in body text |
| `--warn` | `#d97706` | `#f0a43a` | Warning/elevated (= `--state-new`) |
| `--good`, `--bad` | `= --up`, `= --down` | | Status text/icons |
| `--info-bg`, `--warn-bg`, `--good-bg`, `--bad-bg` | 8–12% tints | 15–20% tints | Badge backgrounds |
| `--entity-service` | `#2563eb` | `#6b9cf5` | Service / caller service |
| `--entity-user` | `#c026d3` | `#e07ae8` | Credential/user. **Not purple**, so it can't be confused with `--accent` |
| `--entity-api` | `#0d9488` | `#4fc1b3` | API |
| `--entity-ip` | `#71717a` | `#a1a1aa` | IP |
| `--path-highlight` | `#d97706` | `#f2cc0c` | Topology selected path (was yellow; yellow is unreadable on white) |
| `--http-2xx/3xx/4xx/5xx` | good / info / warn / bad | same roles | HTTP class colors |
| `--series-1` | `var(--accent)` | | Primary chart line |
| `--series-2` | `var(--accent-2)` | | Expected/baseline line (always dashed) |
| `--series-3` | `var(--info)` | | Third series (needs a dash or marker too) |

### 1.3 Rules for this palette

- **Accent changes from blue to purple** (`#6d4ae8` / `#8f74f2`). Blue becomes `--info` and `--entity-service` only.
- **Rounding** follows `DESIGN.md`: card 12px, inner panel 9px, controls 8px, pill 999px. Replace `--radius-panel: 18px` and `--radius-control: 10px`.
- **No gradients** (the `--brand-gradient` / "ProServe" layer goes), **no blur**, **no glow**. Only the chart area fill may use a gradient.

---

## 2. Phases

Work in this order. Each phase ends with these checks:
- `npm run lint`
- `npm run build`
- the browser checks in §7

Do not start phase N+1 until phase N passes.

### Phase A — Token plumbing (no visual change yet)

1. **Write `tokens.css`** with §1 values. Also, temporarily alias the old names to the new roles so nothing breaks:
   - `--theme-canvas: var(--page)`, `--theme-surface: var(--surface)`, `--theme-text: var(--text)`, …
   - `--canvas`, `--surface`, `--text`, `--blue`, …

   Put the aliases at the end of `tokens.css` with a comment `/* legacy aliases — remove in Phase F */`.
2. **`tailwind.config.js`:**
   - Set `darkMode: ['selector', '[data-theme="dark"]']`. This stops `dark:` from following the OS while it still exists.
   - Replace the `colors` block with role names:
     ```js
     page, bg, surface, 'surface-2', line: 'var(--border)', 'line-strong', ink: 'var(--text)', muted, faint,
     accent, 'accent-soft', 'accent-2', info, good, bad, warn, '*-bg' tints, grid, hover, selected,
     entity: { service, user, api, ip }, http: { '2xx','3xx','4xx','5xx' }, 'path-highlight'
     ```
   - Keep the old keys (`canvas`, `panel`, `ink-secondary`, `accent-blue`…) as aliases until Phase F.
   - Remove `brand.*`.
   - Set `borderRadius`: `card: '12px'`, `inner: '9px'`, `ctl: '8px'`.
   - Set `boxShadow`: `card: 'var(--shadow)'`, `pop: 'var(--shadow-pop)'`.
3. **Theme state.** Make `src/theme.ts` read from CSS instead of holding values: `getThemeTokens()` returns `getComputedStyle(document.documentElement).getPropertyValue('--…')` for each role, **memoised per theme**. Then `DARK_THEME`/`LIGHT_THEME` disappear and charts get the same values as CSS.
4. **Move `ThemeContext` out of `App.tsx` into `src/theme.ts`** (provider + `useTheme`) and re-export it from `App.tsx` for compatibility. Keep these unchanged:
   - the storage key `tracescope-theme`;
   - dark as the default (ask the user before changing that);
   - `data-theme` on `<html>`.
5. **Add an inline script to `index.html`** that applies the saved theme before first paint, to avoid a flash.

Done when the app looks the same as before in both themes and lint and build pass.

### Phase B — Shared primitives (most of the visual change)

Restyle these first. Every page inherits them.

| File / item | Target |
|---|---|
| `index.css` base | `body` background `--page`, Inter 14/1.4, `:focus-visible` 2px accent ring, tabular numbers on `.num`, scrollbars from tokens |
| `components.tsx` `Panel` | Double frame: outer `rounded-card border border-line bg-surface-2 p-[3px] shadow-card`, inner `rounded-inner border border-line bg-surface`. Header = uppercase 11.5px muted label + value/title; actions on the right |
| `components.tsx` `MetricCard` / `InteractiveMetricCard` | `StatCard` look: label, 20px value + unit, change `Pill` (direction ≠ tone; TPS neutral, latency/errors up = bad), icon box, foot row. Active state: `ring-1 ring-accent` + `bg-accent-soft` header |
| `Page`, `Loading`, `ErrorState`, empty states | `StateBox` look (muted centered text; error uses `--bad`) |
| Buttons, segmented controls, selects, inputs, search | `DESIGN.md` §6 controls: 8px radius, `line-strong` borders, pressed segment `bg-surface-2 text-ink`, one `primary` (accent fill, white text) per view |
| Badges/pills (`EpisodePrimitives.tsx` status, workflow, priority; HTTP badges) | Status color text + `*-bg` tint + border, 999px, 11.5px. Box-free badges stay box-free (colored text + icon) as currently specified |
| Tables (shared row/header classes) | Header 12.5 muted, row dividers `--border`, hover `--hover`, selected `--selected`, numeric right-aligned `.num` |
| `App.tsx` shell | Side nav: `--bg` background, active item `bg-surface-2 border-line text-accent`, labels muted 12.5. Toolbar: `--bg`, bottom border, breadcrumbs muted/ink. ClickHouse pill uses `good` tokens. Remove gradients from brand mark (solid accent) |
| `EntityLink.tsx` | Entity color only on the icon/dot; the text stays `ink`, with an underline on hover |

Rules:
- Do not change props or component APIs.
- Where a primitive has `isLight ? A : B`, collapse it to the role class.

### Phase C — Charts

1. **`chartTheme.ts`:** one function `chartTokens()` that reads CSS variables (Phase A3). It provides:
   - grid `--grid`;
   - axis labels `--muted` at 11px;
   - axis line `--border`;
   - tooltip `--surface` background, `--border-strong` border, `--shadow-pop`;
   - series colors from `--series-*` and `--http-*`.
2. **Recharts (14 files):**
   - Every `stroke`/`fill` literal → `chartTokens()`.
   - TPS = series-1 with a 10–15% gradient area. Expected/baseline = series-2 **dashed** `4 4`, no area.
   - One zero-based Y axis per chart. Keep any existing documented right-axis overlay, but colour it with tokens.
   - Line width stays `--chart-line-width` (1.5px).
   - No dots except on hover.
3. **ECharts (`ZoomableDashboardChart.tsx`):** same tokens via `chartTokens()`. Dispose and re-initialise (or `setOption`) when the theme changes. Style the zoom slider with `--surface-2`/`--border`.
4. **Re-read colours when the theme changes:** charts subscribe to `useTheme()` so they repaint on toggle.

### Phase D — Graph-heavy components (hex in SVG / inline styles)

Files: `InteractiveTopology.tsx`, `Topology.tsx` (canvas), `AccessFlow.tsx`, `AccessMatrix.tsx`, `AccessExplorer.tsx`, `ServiceAccessBoard.tsx`, `ChangeVisualEvidence.tsx`, `BehaviorGraph.tsx`, `accessEncoding.ts`.

- **`accessEncoding.ts`:** `getStateStyle(state)` and `getEntityColor(kind)` return `var(--state-*)` / `var(--entity-*)` strings. **Remove the `isLight` parameter.** Callers stop passing it.
  - Stroke patterns are unchanged: established solid, learning dashed, ghost dotted, new/deviating orange with glyph. They are the second channel besides colour.
- **SVG:** use `fill="var(--…)"` / `stroke="var(--…)"` directly. CSS variables work in SVG attributes in all target browsers.
- **Which file is live:** `/topology` routes to `InteractiveTopology.tsx`, which is SVG plus DOM cards and contains 221 hex values. That is the main work. `Topology.tsx` (canvas 2D) is not on the `/topology` route; check whether anything else imports it. If it is still used, canvas can't read `var()`: use the memoised `getThemeTokens()` and redraw on theme change.
- **Arrow markers in `InteractiveTopology.tsx`:** `#topology-arrow` and `#topology-arrow-selected` have hard-coded `fill`s. The selected one uses `dark:fill-[#facc15]`, so today it follows the OS, not the app theme. Use `fill="var(--border-strong)"` and `fill="var(--path-highlight)"`. CSS variables resolve inside `<defs>`/`<marker>` in the same document.
- **Topology:**
  - node cards: `--surface` with a `--border` frame, 9px radius;
  - selected node: `--accent` ring;
  - edges: `--border-strong`, active `--info`;
  - selected path `--path-highlight`, keeping the arrow markers;
  - background: plain `--page`, no grid.
- **Floating panels** (inspector, drawer, search dropdown): `--surface`, `--border-strong`, `--shadow-pop`, 12px radius, no blur.

### Phase E — Pages, mechanical sweep

Go file by file, largest first.

**Order:**
1. `UserIntelligence.tsx`
2. `Anomalies.tsx`
3. `AgentStats.tsx`
4. `Services.tsx`
5. `user/UserActivityWorkspace.tsx`
6. `Overview.tsx`
7. `Behavior.tsx`
8. `ApiDetail.tsx`
9. `Changes.tsx`
10. `user/UserLayout.tsx`
11. `UnknownUsers.tsx`
12. `InvestigationPanel.tsx`
13. `Alerts.tsx`
14. `Traces.tsx`
15. `Principals.tsx`
16. `user/UserDirectory.tsx`
17. `user/UserChangesTab.tsx`
18. `FleetTriage.tsx`
19. `Accounts.tsx`
20. the rest

**Step 1 — codemod for the unambiguous neutrals.** Write `scripts/restyle-codemod.mjs` (Node, no dependencies). For each `.tsx`, it:
- replaces whole class tokens using the table below;
- deletes a `dark:` token when its non-dark partner maps to the same role;
- prints every hex/`dark:` token it did **not** map, with file:line.

Run it per file. Review the diff by eye.

| Old class colour(s) | New role class |
|---|---|
| bg `#0b0c0e #0c0d14 #0d0e12 #0e0f12 #0b0914 #0c0e17 #0e1116 #12101b` and light `#f3f4f8 #f3f6fa` | `bg-page` |
| bg `#111217 #141622 #141624 #161424 #161826 #16181f`, light `#ffffff` | `bg-surface` |
| bg `#181b1f #1a172a #202333 #202226 #1f222b #171329 #181a28` and light `#f1f3f5 #f0f3f6 #f1f5f9 #f5f3fa #f8fafc` | `bg-surface-2` |
| border `#2a2d30 #262838 #262a33 #303449 #2d3145`, light `#d5dee9 #e2e8f0 #cbd5e1` | `border-line` |
| border `#34373b #343947` | `border-line-strong` |
| text `#f1f3f5 #f4f5f8 #d8d9da #c9d1d9`, light `#172235 #1f2330` | `text-ink` |
| text `#a7a9ab #c2c6cc #8b949e #9ca3af #7b7d80 #6e7681 #9e96b8`, light `#475569 #64748b` | `text-muted` |
| text `#59616b #5f6573 #94a3b8` | `text-faint` |
| text/bg/border `#73bf69 #16a34a` | `good` (`text-good`, `bg-good-bg`, `border-good`) |
| `#f2495c #dc2626 #fb7185` | `bad` |
| `#ff9830 #d97706` | `warn` |
| `#303236` (grid lines/dividers) | `border-grid` / `divide-grid` |
| `divide-[#…]` | `divide-line` |
| palette `slate/gray/zinc-*` | neutral role by lightness: ≤300 → `line`/`surface-2`, 400–500 → `muted`/`faint`, ≥600 → `ink` |

**Step 2 — manual decisions for the ambiguous colours.** The codemod only lists these:
- **Blue `#5794f2 #1d63dc #3b82f6 #a9ccff`, `blue-*`:**
  - link/selection/active/primary button → `accent`;
  - informational status → `info`;
  - Service entity (icon, node, path, label) → `entity-service`.
- **Purple `#b877d9 #c4bdd9 #d9b4ea #7c3aed`, `violet-*`/`purple-*`:**
  - User/credential entity → `entity-user`;
  - brand/primary → `accent`;
  - secondary chart series → `series-3`.
- **Teal `#56b9a8 #0d9488 #9be7d8`:** API entity → `entity-api`.
- **Yellow `#f2cc0c`:** path highlight → `path-highlight`; anything else → `warn`.
- **`text-white`:** keep only on accent/solid status fills. Otherwise → `text-ink`.

**Step 3 — remove `isLight` branches.** Collapse every `isLight ? 'x' : 'y'` and `theme === "light"` style branch in the file into one role class or a `var()` value.

**Step 4 — layout polish (only what the style needs; no restructuring).**
- **Panels:** sections should use `Panel`. Replace hand-rolled `rounded-xl border bg-[#…]` boxes with `Panel` or its classes.
- **Headings:** reduce oversized headings to the `DESIGN.md` §3 scale. Remove hero banners and gradient strips.
- **Spacing:** use 20px page gaps and 14px panel padding where the current value is arbitrary.

### Phase F — Remove the legacy layer

1. **Delete from `index.css`:**
   - all `[class~="…[#hex]"]` override rules (~125–690);
   - the hover remap blocks;
   - the "ProServe" gradient layer;
   - the old `--theme-*` / `--canvas` definitions.

   Keep only base element styles and true global utilities.
2. **Remove the legacy aliases** from `tokens.css` and `tailwind.config.js`. Fix whatever lint/build or the grep below finds.
3. **Remove `darkMode`** from the Tailwind config if no `dark:` remains. Otherwise keep the selector form.
4. **Final greps — each must print 0:**
   ```sh
   cd frontend
   grep -rhoE "\-\[#[0-9a-fA-F]{3,8}\]" src | wc -l
   grep -rhoE "(^|[ \"'\`])dark:" src | wc -l
   grep -rhoE "\b(bg|text|border|ring|divide)-(slate|gray|zinc|neutral|stone|blue|sky|indigo|violet|purple|fuchsia|pink|rose|red|orange|amber|yellow|lime|green|emerald|teal|cyan)-[0-9]{2,3}" src | wc -l
   grep -rnE "#[0-9a-fA-F]{6}" src --include=*.ts --include=*.tsx | grep -v "styles/tokens.css" | wc -l
   grep -rn "isLight\|theme === \"light\"\|backdrop-blur\|bg-gradient" src | wc -l
   ```
   The only allowed hex values are in `src/styles/tokens.css`.

---

## 3. Theme switch UX

- **Keep the existing toggle**, but make it a two-option segmented control: Light | Dark, with sun/moon icons and `aria-pressed`, as in `frontend-next`'s `ThemeSwitch`.
- **Default stays dark.** If the user wants light as the default, change only the fallback in the provider and in the inline script.
- **No transition animation** when switching themes.

---

## 4. Do not change

- Routes, API calls, query keys, data maths (completed buckets, dense filling, FINAL-based numbers), sorting/paging logic.
- i18n strings and keys. Visible text stays as it is, **except** text that is part of the old style (hero copy, "ProServe" banners): remove those and leave a note.
- Interaction behaviour documented in `AGENTS.md`:
  - Access flow hover/selection rules;
  - topology drag/zoom/highlight;
  - KPI overlay semantics;
  - Changes layout decisions such as box-free badges and the divider.
- The non-colour channels of state encoding: dash patterns, glyphs, labels.

---

## 5. Work units and order

Each unit is one reviewable diff:

1. Phase A (tokens, Tailwind, theme provider, inline script)
2. Phase B (primitives + shell)
3. Phase C (charts)
4. Phase D (graph components)
5. Phase E, in batches of 2–4 pages, per the order in §2E
6. Phase F (cleanup + greps)
7. `AGENTS.md` update + serve

Rough effort:

| Phase | Effort |
|---|---|
| A | 0.5 d |
| B | 1 d |
| C | 0.5 d |
| D | 1.5 d |
| E | 3 d |
| F | 0.5 d |

**Total: about 7 working days.**

---

## 6. Serving

- Build output stays `frontend/dist`. FastAPI already serves it.
- After each unit you want live, run `npm run build`; FastAPI on `:31102` picks it up without a restart.
- **Cluster (`:30102`) and the image:** only update them when the user asks. Never use `kubectl`.

---

## 7. Verification (every unit)

1. `npm run lint` and `npm run build` are clean.
2. **Chromium script** (`.venv/bin/python`, Playwright, as used before in this repo, e.g. `backend/scripts/test_pages_playwright.py`). For each route below, at **1440×900 light, 1440×900 dark, 390×844 light**:
   - 0 page errors and 0 console errors;
   - `document.documentElement.scrollWidth <= innerWidth`;
   - a screenshot saved to the scratchpad.

   Routes:

   | Area | Routes |
   |---|---|
   | Dashboard | `/dashboard` |
   | Services and APIs | `/services`, `/services/order-service`, `/apis`, `/services/order-service/apis/POST%20%2Fapi%2Fv1%2Forders%2Fprocess` |
   | Users | `/users`, `/users/alice_wsse/activity`, `/users/alice_wsse/changes` |
   | Changes and alerts | `/changes`, one `/changes/:id` taken from `/api/v1/changes`, `/alerts` |
   | Topology and behavior | `/topology`, `/behavior`, `/behavior?tab=flow`, `/behavior?tab=matrix` |
   | Traces and agents | `/traces`, one trace detail, `/agent-stats` |

3. **Theme toggle test:** switch on `/dashboard` and `/topology`. Charts, canvas and SVG must repaint with no stale colours, and there must be no flash on reload in either theme.
4. **Contrast spot-check** (computed styles, WCAG AA 4.5:1) in both themes, on these pairs:
   - `--text`, `--muted` and each status colour, all on `--surface`;
   - pill text on its tint;
   - `--accent` on `--surface`.
5. **Interaction regressions:**
   - Access explorer selection;
   - topology drag/zoom/path highlight;
   - KPI overlay toggle;
   - Changes filters;
   - chart tooltips.

---

## 8. Risks and how to avoid them

| Risk | Mitigation |
|---|---|
| Codemod maps a colour to the wrong role (blue/purple meaning) | The codemod only does the neutrals and status colours; it lists blue/purple/teal/yellow for manual choice (§2E step 2) |
| Light/dark pairs (`text-[#172235] dark:text-[#…]`) collapse wrongly | Collapse a pair only when both sides map to the same role; otherwise list it for manual review |
| Charts keep old colours after a toggle | Phase C4: subscribe to `useTheme()`; canvas redraw in Phase D |
| Removing the override block in Phase F reveals literals that were missed | The Phase F greps must be 0 before deleting; then run the full §7 pass |
| Dark mode looks worse than before | Dark is part of the design, not an inversion: use the `frontend-next` dark set and review dark screenshots in every unit |
| Another agent is editing `frontend/` at the same time | Check `git status` / `git diff --stat frontend/` before each unit; don't overwrite others' changes |

---

## 9. 60/30/10 Color Architecture & Budget Rules

### 9.1 Tier Allocation
| Tier | Share | Tokens / Roles | Usage Rules |
|---|---|---|---|
| **60 Base** | 55–68% | `--page`, `--bg`, `--surface`, `--surface-2`, `--hover` | Page background, cards, table rows, standard text/borders. |
| **30 Structure** | 22–35% | `--structure`, `--structure-2`, `--structure-border`, `--structure-text` | Sidebar rail, top toolbar, table header strips, segmented control backgrounds, panel headers, pill containers. |
| **10 Accent** | ≤ 10% | `--accent` (`#6d28d9` / `#8b5cf6`), `--accent-soft` | Primary CTA button (max 1 per view), active tab indicator/mark, selected row/node highlight, primary chart series (TPS). |
| **Semantic** | ≤ 5% | `--good`, `--bad`, `--warn`, `--info`, `--entity-*` | Small status badges, alert severity badges, entity type marks. Tinted backgrounds only on small badges. |

### 9.2 Enforcement & Budget Guard
Run `npm run check:colors` or `sh frontend/scripts/check-color-budget.sh`. Must exit 0:
- `text-accent (incl. hover)`: ≤ 45
- `border-accent`: ≤ 25
- `solid bg-accent`: ≤ 15
- `bg-accent/NN tints`: 0
- `accent-2`: 0
- `undefined vars`: 0
- `status opacity fills`: 0
- `status -bg tints (badges)`: ≤ 45
- `arbitrary hex classes`: 0
- `dark: variants`: 0

