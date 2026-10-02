# 60/30/10 Color Implementation Plan (frontend/)

Status: implemented 2026-10-02; follow-ups in docs/color-60-30-10-fixes.md.
Audience: an implementing agent with no prior context. Follow the steps in order; each phase ends with a checkpoint that must pass before the next one starts.

---

## 0. Ground rules (read first)

1. Start every response to the user with `I HAVE FOLLOW THE RULE xHatsu DEFINED FOR ME BY DEFAULT` (workspace rule).
2. Scope is **`frontend/` only**. Do not touch `backend/`, `deploy/`, Helm, or the cluster. Never run `kubectl`.
3. Shell scripts must be POSIX `sh` (no `[[ ]]`, `local`, `declare`, `&>`, `source`, arrays).
4. The working tree is dirty with unrelated, uncommitted work. **Do not** `git checkout`, `git stash`, `git reset` or reformat files. Edit only the lines you need. Do not commit unless the user asks.
5. Work from `/home/ubuntu/Viettel/OtelTrace/frontend`. Build with `npm run build`. The local server on `:31102` serves `frontend/dist` directly; a rebuild is enough, no restart needed.
6. Keep EN/VI copy untouched; this is a color-only change. Do not change layout, spacing, sizes, or component behaviour.
7. All colors go through tokens. Never add a raw hex/rgb literal to `.ts/.tsx` (existing guard grep #4 must stay 0). New raw values are allowed only in `src/styles/tokens.css`.
8. After finishing, update `AGENTS.md` (replace the "60/30/10 color plan" section) and `STATE.md` with what was done and verified.

---

## 1. Target model

| Tier | Share of pixels | Role | Token(s) |
|---|---|---|---|
| **60 base** | ~60% | Calm canvas: page background, card bodies, chart plot areas, table bodies | `--page`, `--surface`, `--bg`, `--surface-2` |
| **30 structure** | ~30% | The frame: sidebar rail, top bar, card/panel headers, table header rows, chips, segmented controls, inactive tabs, neutral badges | **new** `--structure`, `--structure-2`, `--structure-border`, `--structure-text` |
| **10 accent** | ≤10% | Only "where am I / what do I act on": primary button, active nav item, selected row/item, active tab indicator, focus ring, the single primary chart series | `--accent`, `--accent-soft` |
| Semantic (outside split) | ≤5% on calm data | Status (good/warn/bad/info), entity identity (service/user/API/IP), HTTP classes | existing tokens |

**Semantic layer rule:** status/entity colors appear only as *small marks*: text, icon, dot, 1–2 px line/left border, small badge with a `-bg` tint. No large tinted panels or opacity fills (`bg-warn/10` etc.) unless the element is an actual error/critical banner.

**Decision default:** the 30 tier is a **tinted light neutral** (option a). If the user later picks option b (dark rail + top bar in light mode), only the four `--structure*` values in the light block of `tokens.css` change (see §3.1 alt values); everything else in this plan is identical.

---

## 2. Baseline inventory (measured 2026-10-02, use to confirm you are on the same tree)

Run from `frontend/`:

```sh
grep -rhoE '\btext-accent([^-a-z0-9/]|$)' src | wc -l      # 132 (incl. 23 hover:)
grep -rhoE '\bborder-accent(/[0-9]+)?\b' src | wc -l        # ~56 in .ts/.tsx (guard script, incl. .css: 64)
grep -rhoE 'bg-accent/[0-9]+' src | wc -l                   # 62
grep -rhoE 'accent-2' src | wc -l                           # 8 in .ts/.tsx (guard script, incl. .css: 11)
grep -rhoE 'var\(--(text-muted|border-line)\)' src | wc -l  # 40 (undefined vars, a bug)
grep -rhoE 'bg-(good|bad|warn|info)(-bg|/[0-9]+)' src | wc -l   # ~105
```

Per-file accent + tint load (sum | text-accent | hover:text-accent | border-accent | solid bg-accent | bg-accent/NN | bg-accent-soft | status tints | var(--accent)):

```
102 pages/Anomalies.tsx              12|2|8|12|41|0|25|2
 51 pages/UserIntelligence.tsx        0|1|6|7|7|0|15|15
 29 pages/AgentStats.tsx              0|3|1|0|1|0|17|7
 25 pages/InteractiveTopology.tsx    11|0|7|2|0|2|3|0
 22 pages/Overview.tsx               11|5|0|1|2|2|0|1
 19 pages/user/UserLayout.tsx         5|0|6|0|0|3|5|0
 19 pages/Behavior.tsx               11|0|3|0|0|0|0|5
 18 pages/Services.tsx               11|2|1|0|0|1|3|0
 17 pages/ApiDetail.tsx               8|1|3|0|0|3|2|0
 17 components/EpisodePrimitives.tsx  5|0|2|1|0|2|7|0
 15 App.tsx                           6|0|3|3|0|1|2|0
 14 pages/user/UserDirectory.tsx      1|0|1|2|2|0|8|0
 14 pages/UnknownUsers.tsx            0|0|1|4|3|0|3|3
 14 pages/Changes.tsx                 5|4|3|0|2|0|0|0
 13 pages/Traces.tsx                  0|1|3|0|2|0|7|0
 12 pages/user/UserActivityWorkspace  6|0|1|0|0|1|3|1
 11 components/AccessFlow.tsx         4|0|3|0|0|3|1|0
  9 components.tsx                    2|0|1|1|0|1|2|2
  7 pages/Topology.tsx                2|0|3|0|0|2|0|0
  7 components/FleetTriage.tsx       2|2|1|0|1|1|0|0
  7 components/AccessMatrix.tsx       2|0|2|0|0|2|0|1
  5 theme.tsx  (token plumbing)
  4 pages/user/UserChangesTab.tsx, components/AccessExplorer.tsx
  3 pages/Principals.tsx, pages/Accounts.tsx, components/ChangeVisualEvidence.tsx
  1 pages/BehaviorGraph.tsx, i18n.tsx, components/InvestigationPanel.tsx
```

Undefined vars live in: `Behavior.tsx` 12, `UserIntelligence.tsx` 12, `BehaviorGraph.tsx` 4, `UnknownUsers.tsx` 3, `Accounts.tsx` 2, `Anomalies.tsx` 2, `Overview.tsx` 2, `Principals.tsx` 2, `index.css` 1.

---

## 3. Phase 1 — Tokens (≈0.5 day)

### 3.1 `src/styles/tokens.css`

In the light `:root` block, add after the `/* Borders */` group:

```css
  /* Structure (30 tier) */
  --structure: #eef0f5;
  --structure-2: #e3e6ee;        /* hover / pressed on structure */
  --structure-border: #dde1ea;
  --structure-text: #3f3f46;
```

In `:root[data-theme="dark"]` add:

```css
  /* Structure (30 tier) */
  --structure: #141519;
  --structure-2: #1d1f25;
  --structure-border: #272a31;
  --structure-text: #d4d4d8;
```

Dark `--page` (`#0c0c0e`) and `--surface` (`#18181b`) stay. The structure tone sits between them on purpose so the frame reads separately from both.

Option b (dark rail in light mode) alt values for the light block only: `--structure: #1f2029; --structure-2: #2a2c37; --structure-border: #2f3140; --structure-text: #e4e4e7;`. If chosen, nav text/icons in the rail must use `text-structure-ink` (never `text-muted`/`text-ink`), and the contrast check in Phase 5 must be rerun.

Also in **both** blocks:

```css
  /* Aliases for previously undefined vars (bug fix). Removed in Phase 4. */
  --text-muted: var(--muted);
  --border-line: var(--border);
```

Chart series, both blocks:

```css
  --series-1: var(--accent);
  --series-2: var(--muted);   /* was var(--accent-2): expected/baseline is a neutral reference line */
  --series-3: var(--info);
```

Leave `--accent-2` defined for now (still referenced; removed in Phase 4).

### 3.2 `tailwind.config.js` → `theme.extend.colors` add:

```js
        structure: 'var(--structure)',
        'structure-2': 'var(--structure-2)',
        'structure-line': 'var(--structure-border)',
        'structure-ink': 'var(--structure-text)',
```

### 3.3 `src/theme.tsx`

- `sidebar:` → read `--structure` (both the computed branch, `readCssVar("--structure", "var(--structure)")`, and the fallback object `"var(--structure)"`).
- `chart.baseline:` → `muted` / `"var(--muted)"` (was accent2).
- `yellow:` → `warn` / `"var(--warn)"` (keeps a yellow-ish key working without the second accent).
- If `ColorTokens` needs a new field, add `structure: string` and populate it in both places. Do not remove existing keys (consumers: `chartTheme.ts`, `investigationView.ts`, `Behavior.tsx`, `Topology.tsx`).

### Checkpoint 1
```sh
npm run lint && npm run build
grep -rhoE 'var\(--(text-muted|border-line)\)' src | wc -l   # still 40 but now resolve (aliases)
```
Open `http://127.0.0.1:31102/behavior` → axis tick labels must now be grey (`--muted`), not black. Expected/baseline lines on Overview, Services, Behavior, ChangeVisualEvidence are now grey dashed.

---

## 4. Phase 2 — Shell and shared primitives = the 30 tier (≈1 day)

### 4.1 `src/App.tsx` sidebar (`<aside className="app-rail ...">`, ~line 129)
| Element | Now | Change to |
|---|---|---|
| `<aside>` | `bg-bg border-r border-line` | `bg-structure border-r border-structure-line` |
| Brand tile | `bg-accent text-white` | keep (single brand accent mark) |
| "Intelligence" subtitle | `text-accent` | `text-structure-ink/70` → if opacity looks wrong use `text-muted` |
| Group labels | `text-muted` | keep |
| Inactive link | `text-muted hover:bg-hover hover:text-ink` | `text-structure-ink/80 hover:bg-structure-2 hover:text-ink` |
| Active link | `bg-surface-2 border border-line text-accent font-semibold` | `bg-accent-soft text-ink font-semibold` (drop the border) |
| Active left bar | `bg-accent` | keep |
| Active icon | `text-accent` | keep (icon + bar = the rail's only accent) |
| Inactive icon | `text-muted group-hover:text-ink` | keep |
| Footer divider | `border-line` | `border-structure-line` |
| ClickHouse pill (`border-good-bd bg-good-bg`) | keep: small semantic mark |

`FilterBar` retry link (~line 512) `text-accent underline` → `text-ink underline`.
Any remaining `text-accent` in App.tsx: keep only if it marks the *current* selection (e.g. active theme/language toggle); else `text-ink`/`text-muted`.

### 4.2 `src/index.css` (`@layer components`)
| Rule | Change |
|---|---|
| `.toolbar` | `background: var(--structure); border-bottom: 1px solid var(--structure-border);` |
| `.toolbar-control` | `background: var(--surface);` (controls sit as base on the structure bar) |
| `.panel-header` | `background: var(--structure); border-bottom: 1px solid var(--structure-border);` |
| `.table-head` | add `background: var(--structure);` (if it is applied to `<th>` only and rows look striped, apply to the `<thead><tr>` usage instead) |
| `.chip` | `background: var(--structure); border-color: var(--structure-border);` |
| `.btn` | keep `var(--bg)` base; `:hover` → `var(--structure-2)` |
| `.btn-primary` family | keep accent (this is the 10 tier) |
| `.label` | keep |

Find other shell CSS that should be structure: `grep -nE 'segment|tabs?\b|tab-' src/index.css`. Segmented-control containers and inactive tabs → `--structure`; the *active* segment → `--surface` + `--text` + (optional) 2 px accent underline.

### 4.3 `src/components.tsx`
- `Panel` header / `MetricCard` label strip: use `.panel-header` (now structure) — no class changes if they already use it; if they use `bg-surface-2` for headers, switch to `bg-structure`.
- `text-accent` (2): keep only on an active/selected state; else `text-ink`.
- Solid `bg-accent` (1): keep only if it is a primary CTA / progress bar.
- `var(--accent)` (2): if it is the TPS line → keep (primary series). Area gradient stays accent-only.

### 4.4 `src/components/EntityLink.tsx`
Link text → `text-ink hover:underline`; the entity colour only on the leading icon/dot (`text-entity-*`). No `text-accent`.

### 4.5 `src/components/EpisodePrimitives.tsx`
- Status badges: keep text colour; tinted bg only for small badges (`bg-*-bg`). `EpisodeCard` body `bg-surface`, card header row `bg-structure` if it has one.
- `text-accent` (5) → `text-ink`/`text-muted` unless selected state.

### Checkpoint 2
`npm run build`, then load `/dashboard`, `/services`, `/changes` in light and dark. Expect: sidebar, top bar and every panel header visibly a second tone; page/card bodies unchanged; active nav item is the only violet in the rail.

---

## 5. Phase 3 — Accent and semantic sweep (≈2–2.5 days)

### 5.1 Decision table (apply mechanically, then eyeball)

| Pattern | Replace with | Keep accent ONLY when the element is… |
|---|---|---|
| `text-accent` on links, entity names, "View all", labels, numbers | `text-ink` + `hover:underline` (links) or `text-muted` (labels) | the active tab label, the selected list item, the single primary KPI value |
| `hover:text-accent` | `hover:text-ink` (+ `hover:underline` on links) | — never |
| `border-accent`, `border-accent/40..50` | `border-line-strong` | selected card/row/item, focused input |
| solid `bg-accent` (+ `text-white`) | `.btn` neutral (`bg-bg border-line-strong text-ink`) or `bg-structure` | primary CTA (max 1 per view), active toggle knob, progress/strength bar, brand tile |
| `bg-accent/10..80` tints | `bg-structure` (blocks, headers, pills) or `bg-hover` (hover rows) | selected row → `bg-accent-soft` (not `/NN`) |
| `bg-accent-soft` | keep only for selected/active | — |
| `ring-accent` / `focus-visible:ring-accent` | keep (accessibility) | — |
| `var(--accent)` in charts | keep for the one primary series (TPS/observed); other series → `var(--info)`, `var(--muted)` dashed, or entity tokens | — |
| `var(--accent)` in SVG graphs (topology/flow/matrix) | selection highlight only; resting nodes/edges → `var(--border-strong)` / entity tokens | — |
| `bg-(good|bad|warn|info)/NN` fills | neutral surface + `border-l-2 border-<status>` or a small dot `h-2 w-2 rounded-full bg-<status>` | real error/critical banner → `bg-bad-bg border-bad-bd` |
| `bg-*-bg` on large panels/sections | `bg-surface` + coloured left border/icon | small badges/pills (`px-1.5 py-0.5 text-[10-11px]`) keep `bg-*-bg` |
| `text-accent-2`, `border-accent-2`, `var(--accent-2)` | `text-warn`/`var(--muted)` depending on meaning (baseline → muted dashed; attention → warn) | — |

Rule of thumb per view: count violet things visible at once. More than ~5 small elements or any large violet area → too many.

### 5.2 File order and specific notes
Do one file at a time; after each: `npm run lint`, then view the page.

1. **`pages/Anomalies.tsx` (102)** — biggest. 41 `bg-accent/NN` tints are perspective switcher/cards/badges: switcher container → `bg-structure`, active segment → `bg-surface text-ink` + accent underline; cards → `bg-surface`; badges → `bg-structure text-ink`. 12 solid `bg-accent`: keep only primary action(s). 25 status tints → small-mark rule. Fix 2 undefined vars (`var(--text-muted)` → `var(--muted)`, `var(--border-line)` → `var(--border)`).
2. **`pages/UserIntelligence.tsx` (51)** — 15 `var(--accent)` are chart/SVG colours: one primary series stays accent; others → `var(--info)` / entity tokens. Fix 12 undefined vars.
3. **`pages/AgentStats.tsx` (29)** — 17 status tints (node health): cards neutral + status dot/left border; keep badge tints. 7 `var(--accent)` in charts: one series accent, rest info/muted.
4. **`pages/InteractiveTopology.tsx` (25)** — 11 `text-accent`: search hits / link text → ink; selected node/inspector title may keep accent. `border-accent` only on selected node card. Path highlight already uses `--path-highlight`; leave it.
5. **`pages/Overview.tsx` (22)** — 11 `text-accent` + 5 hover: "View all", sortable headers, user/service names → ink; active sort column header may stay accent (it is a selection state). Fix 2 undefined vars.
6. **`pages/user/UserLayout.tsx` (19)** — nav tabs container → `bg-structure`; active tab → `bg-surface text-ink` + 2 px accent bottom border; inactive → `text-structure-ink`. Back button neutral.
7. **`pages/Behavior.tsx` (19)** — 11 `text-accent` → ink/muted; 5 `var(--accent)` charts: TPS line stays, `expected_tps` already `--accent-2` → `var(--series-2)`. Fix 12 undefined vars.
8. **`pages/Services.tsx` (18)**, **`pages/ApiDetail.tsx` (17)** — links → ink; tab bars → structure tier; selected tab/row keeps accent-soft.
9. **`components/EpisodePrimitives.tsx`** (if not finished in Phase 2), **`App.tsx`** leftovers.
10. **`pages/user/UserDirectory.tsx`, `UnknownUsers.tsx` (+3 undefined), `Changes.tsx`, `Traces.tsx`, `UserActivityWorkspace.tsx`.**
11. **`components/AccessFlow.tsx`, `AccessMatrix.tsx`, `AccessExplorer.tsx`, `FleetTriage.tsx`, `ChangeVisualEvidence.tsx`** — SVG/canvas: accent only on selected item/ribbon highlight; resting state neutral/entity/state colours from `accessEncoding.ts` (leave `accessEncoding.ts` state colours as is — they are semantic).
12. Remainder: `Topology.tsx`, `UserChangesTab.tsx`, `Principals.tsx` (+2), `Accounts.tsx` (+2), `BehaviorGraph.tsx` (+4), `InvestigationPanel.tsx`, `i18n.tsx` (1 `text-accent` in a component — treat like links).
13. `src/index.css` line using `var(--text-muted)` → `var(--muted)`.

Helpful finder per file:
```sh
grep -nE 'accent|bg-(good|bad|warn|info)(-bg|/[0-9]+)|var\(--(text-muted|border-line)\)' src/pages/Anomalies.tsx
```

### Checkpoint 3
```sh
npm run lint && npm run build
sh scripts/check-color-budget.sh     # written in Phase 4; may run early, must pass at end of Phase 3
```

---

## 6. Phase 4 — Cleanup and guard (≈0.5 day)

1. Confirm zero uses: `grep -rnE 'var\(--(text-muted|border-line)\)|accent-2' src` → only `tokens.css`/`theme.tsx` definitions. Then delete the two aliases and `--accent-2` (both theme blocks), drop `accent2` reads from `theme.tsx`, remove `'accent-2'` from `tailwind.config.js`.
2. Create `frontend/scripts/check-color-budget.sh`:

```sh
#!/bin/sh
# 60/30/10 color budget guard. Run from anywhere: sh frontend/scripts/check-color-budget.sh
cd "$(dirname "$0")/.." || exit 2
fail=0

count() {
  grep -rhoE "$1" src --include=*.ts --include=*.tsx --include=*.css 2>/dev/null | wc -l | tr -d ' '
}

check() {
  n=$(count "$2")
  if [ "$n" -gt "$3" ]; then
    echo "FAIL $1: $n > $3"
    fail=1
  else
    echo "ok   $1: $n <= $3"
  fi
}

check "text-accent (incl. hover)"   '\btext-accent([^-a-z0-9/]|$)'          45
check "border-accent"               '\bborder-accent(/[0-9]+)?\b'            25
check "solid bg-accent"             '\bbg-accent([^-a-z0-9/]|$)'             15
check "bg-accent/NN tints"          'bg-accent/[0-9]+'                        0
check "accent-2"                    'accent-2'                                0
check "undefined vars"              'var\(--(text-muted|border-line)\)'       0
check "status opacity fills"        'bg-(good|bad|warn|info)/[0-9]+'          0
check "status -bg tints (badges)"   'bg-(good|bad|warn|info)-bg'             45
# restyle guards (must stay 0)
check "arbitrary hex classes"       '\-\[#[0-9a-fA-F]{3,8}\]'                 0
check "dark: variants"              '(^|[ "'"'"'`])dark:'                     0

exit $fail
```
`chmod +x` it. Must exit 0. Note `accent-2` budget 0 requires step 1 first.

3. Optionally wire it: add `"check:colors": "sh scripts/check-color-budget.sh"` to `package.json` scripts (do **not** chain into `build`).
4. Update `docs/frontend-restyle-plan.md` (append a short "60/30/10 tiers" section with §1 table + §5.1 rules) so future agents keep the budget.

### Checkpoint 4
`npm run lint && npm run build && sh scripts/check-color-budget.sh` all exit 0. Also the five original restyle greps (see AGENTS.md "Frontend Complete In-Place Restyle") still return 0.

---

## 7. Phase 5 — Verification (≈0.5 day)

### 7.1 Pixel-share measurement
`PIL` is not installed; measure in the browser. Create `/tmp/claude-*/.../scratchpad/color_share.py` (scratch, not committed) and run with `../.venv/bin/python` (Playwright + Chromium are installed in `.venv`):

```python
import asyncio, base64, json
from playwright.async_api import async_playwright

BASE = "http://127.0.0.1:31102"
ROUTES = ["/dashboard", "/services", "/services/order-service",
          "/services/order-service/apis/POST%20%2Fapi%2Fv1%2Forders%2Fprocess",
          "/users/alice_wsse/activity", "/changes", "/topology", "/behavior"]

JS = """async (b64) => {
  const img = new Image(); img.src = 'data:image/png;base64,' + b64; await img.decode();
  const c = document.createElement('canvas'); c.width = img.width; c.height = img.height;
  const x = c.getContext('2d'); x.drawImage(img, 0, 0);
  const d = x.getImageData(0, 0, c.width, c.height).data;
  const cs = getComputedStyle(document.documentElement);
  const hex = v => { const s = v.trim(); if (!s.startsWith('#')) return null;
    return [1,3,5].map(i => parseInt(s.slice(i, i+2), 16)); };
  const tiers = {
    base: ['--page','--bg','--surface','--surface-2','--hover'],
    structure: ['--structure','--structure-2'],
    accent: ['--accent','--accent-soft'],
    semantic: ['--good','--bad','--warn','--info','--entity-service','--entity-user','--entity-api'],
  };
  const pal = [];
  for (const [t, names] of Object.entries(tiers)) for (const n of names) {
    const rgb = hex(cs.getPropertyValue(n)); if (rgb) pal.push([t, rgb]); }
  const counts = {base:0, structure:0, accent:0, semantic:0, other:0}; let total = 0;
  for (let i = 0; i < d.length; i += 16) {           // sample every 4th pixel
    total++; let best = 'other', bd = 30*30*3;          // tolerance: text/borders fall into 'other'
    for (const [t, [r,g,b]] of pal) { const dd = (d[i]-r)**2 + (d[i+1]-g)**2 + (d[i+2]-b)**2;
      if (dd < bd) { bd = dd; best = t; } }
    counts[best]++; }
  const out = {}; for (const k in counts) out[k] = +(100*counts[k]/total).toFixed(1); return out;
}"""

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        for theme in ("light", "dark"):
            pg = await b.new_page(viewport={"width": 1440, "height": 900})
            await pg.add_init_script(f"localStorage.setItem('tracescope-theme','{theme}')")
            errors = []; pg.on("pageerror", lambda e: errors.append(str(e)))
            for r in ROUTES:
                await pg.goto(BASE + r, wait_until="networkidle"); await pg.wait_for_timeout(1500)
                shot = base64.b64encode(await pg.screenshot()).decode()
                print(theme, r, json.dumps(await pg.evaluate(JS, shot)), "errors:", len(errors))
                await pg.screenshot(path=f"/tmp/color-{theme}-{r.strip('/').replace('/','_')[:40] or 'root'}.png")
            await pg.close()
        await b.close()
asyncio.run(main())
```

**Pass targets** (on base+structure+accent+semantic, ignoring `other` = text/borders/antialiasing):
- base 55–68 %, structure 22–35 %, accent ≤ 10 %, semantic ≤ 5 % on each route, both themes.
- Topology/Behavior graphs may exceed semantic 5 % (entity colours are their content) — record but do not fail.
Record a before (run it once **before Phase 1**) and after table and put both in the final report.

### 7.2 Contrast (WCAG AA ≥ 4.5:1 for text)
Check, both themes: `--structure-text` on `--structure`; `--text` on `--structure`; `--muted` on `--structure`; `--accent` on `--structure` (active icon); `--text` on `--accent-soft` (active nav). Use a tiny Python contrast function (relative luminance formula) on the hex values from `tokens.css`. Adjust `--structure*` values if any fail; never lower text contrast.

### 7.3 Regression
```sh
cd /home/ubuntu/Viettel/OtelTrace
.venv/bin/python backend/scripts/test_pages_playwright.py     # all pages, 0 page errors
```
Also 390×844 viewport on `/dashboard` and `/services/order-service`: no horizontal document overflow.

### 7.4 Visual spot-check (manual, screenshots from 7.1)
- Only one violet "where am I" mark in the sidebar.
- No page shows a large violet area; primary button(s) still clearly violet.
- Expected/baseline chart lines grey dashed; observed TPS violet.
- Status still readable at a glance (dots/badges/left borders), errors still red.
- Dark mode: structure tone visibly between page and card.

---

## 8. Definition of done

- [ ] Checkpoints 1–4 pass; `npm run build` clean.
- [ ] `sh frontend/scripts/check-color-budget.sh` exits 0.
- [ ] Pixel-share after-table meets §7.1 targets on all 8 routes in both themes (graphs excepted).
- [ ] Contrast pairs in §7.2 ≥ 4.5:1.
- [ ] Playwright page suite 0 page errors; 390 px no overflow.
- [ ] `frontend/dist` rebuilt and served on `:31102` (HTTP 200 on `/` and `/api/v1/health`).
- [ ] `AGENTS.md` section "60/30/10 color plan" replaced with an "implemented" entry (what changed, budgets, before/after shares, verification); `STATE.md` updated.
- [ ] No commit, no cluster/image changes (cluster image does not include this; note it).

## 9. Rollback

All changes are in `frontend/src`, `frontend/tailwind.config.js`, `frontend/scripts/check-color-budget.sh`, docs. Because the tree has unrelated uncommitted work, roll back by reverting only these hunks (e.g. `git diff -- frontend/src/styles/tokens.css` and reverse-apply that file's hunks), not with `git checkout` on whole directories. Quick visual rollback without code revert: set the four `--structure*` tokens equal to `--surface` and `--series-2` back to `var(--accent-2)`.

## 10. Effort

| Phase | Est. |
|---|---|
| 1 Tokens + undefined-var fix | 0.5 day |
| 2 Shell + primitives (30 tier) | 1 day |
| 3 Accent/semantic sweep (~200 accent + ~105 tint sites, 30 files) | 2–2.5 days |
| 4 Cleanup + guard script | 0.5 day |
| 5 Verification | 0.5 day |
| **Total** | **≈4.5–5 days** |
