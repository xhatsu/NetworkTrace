# Plan: replace `frontend/` with `frontend-next/`

**Goal:** rebuild every page people use in `frontend-next`, using the style in `DESIGN.md`. When the new app covers them, switch FastAPI to serve `frontend-next/dist` and retire `frontend/`.

**Rule:** the old app stays live on `:31102` / `:30102` until the cutover in Phase 7. Nothing in `frontend/` changes, apart from the optional stopgap at the end of this file.

**How to use the old app:** treat it as a behaviour reference only. Read its API calls, response types and data rules. Do not copy its JSX or CSS.

---

## Phase 0 — Foundation (do first, about 1 day)

| Item | Decision |
|---|---|
| Routing | Add `react-router-dom` and use real paths, not `#/`. Paths stay the same as the old app so links and bookmarks keep working: `/dashboard`, `/services/:name`, `/services/:svc/apis/:api`, `/apis`, `/users/:p/activity`, `/users/:p/changes/:id`, `/changes/:id`, `/topology`, `/behavior`, `/traces/:id`, `/agent-stats/:node`. `/` redirects to `/dashboard`. |
| App shell | Move the topbar and range into an `AppLayout` with an `<Outlet/>`. `Sidebar` uses `NavLink`, and the active item comes from the route. |
| Global filters | Range (1h/3h/6h/24h/7d) and refresh nonce live in a `FiltersProvider` and are mirrored in the URL (`?range=`), so links keep the context. |
| Data | Keep `useApi`. Add `refetchMs` (default 60 s, paused when the tab is hidden) and a small in-memory cache keyed by URL for back navigation. Move to TanStack Query only if caching grows complicated. |
| i18n | The old UI defaults to Vietnamese. Add `src/i18n.tsx` with `t(en, vi)` and a VI/EN switch in the topbar saved to `localStorage["ts-lang"]`. Keep product terms in English: Service, API, User, TPS, P95, Trace, IP. **Every new string needs both languages.** |
| Shared parts | Add `EntityLink` (Service/API/User/Change routes), `Tabs` (`.seg` that syncs with `?tab=`), `Pager` (15-row pages), `SortHeader`, and `KpiCard` (a clickable `StatCard` that toggles a chart overlay). |
| Mobile nav | A topbar menu button that opens `Sidebar` as an overlay at ≤760px. |
| Dev server | Already on `:31110` proxying `/api` to `:31102`. |

**Done when:**
- every route renders a placeholder card inside the shell;
- deep links load on refresh (preview fallback);
- the build is clean.

---

## Phases 1–6 — Pages (one PR-sized step each, in this order)

For each page: list the endpoints the old page uses, then build it with the `DESIGN.md` primitives. It must have loading, empty and error states, VI/EN text, and pass the browser checks (Phase 7 list).

| Phase | Pages | Main endpoints | Notes |
|---|---|---|---|
| **1 Dashboard** | `/dashboard` | `/dashboard/series`, `/services`, `/behavior/access?view=lists`, `/changes`, `/topology/bandwidth`, `/users` | Mostly built. Add a bandwidth stat, important changes, Top users with sorting, and the weekday × hour heatmap of when changes start. |
| **2 Services and APIs** | `/services`, `/services/:name`, `/apis`, `/services/:svc/apis/:api` | `/services`, `/services/{s}`, `/apis`, `/dashboard/series?service&operation`, `/topology/services/{s}/ips`, `/topology/apis/{api}/metrics`, `/changes` | Catalog: search, environment filter, sorting, 10/15-row pages. Detail: 5 KPI cards with overlays, TPS vs expected, recent changes beside it, Access explorer, and tabs for APIs/Users/Callers/Instances/Traces. |
| **3 Users** | `/users`, `/users/:p/activity`, `/users/:p/changes`, `/users/:p/changes/:id` | `/users`, `/users/{p}`, `/principals/{p}/metrics`, `/behavior/access?view=lists&scope=credential`, `/topology/principals/{p}/ips`, `/user-changes` | The activity page has the same layout as Service detail, plus a request outcome chart and an active-hour heatmap. |
| **4 Changes** | `/changes`, `/changes/:id` | `/changes`, `/changes/{id}`, `/dashboard/series?caller&service`, `/investigations*`, alert and review endpoints | List: count tabs, filters saved in the URL, 25-row pages. Detail: change in context (1-minute dense buckets, saved detector reference vs observed), Jev result beside it, timeline, evidence, operator decisions, LLM investigation. |
| **5 Behavior and Topology** | `/topology`, `/behavior?tab=…` | `/behavior/topology`, `/behavior/topology/detail`, `/behavior/access` (flow, matrix, lists), `/behavior/overview` | Heaviest step. The canvas (drag, zoom, spider layout, highlighted paths) and the Sankey/matrix are plain SVG. Port the layout logic (`topologyLayout`, `accessLayout`) as pure modules, then re-skin. |
| **6 Remaining** | `/traces`, `/traces/:id`, `/agent-stats`, `/agent-stats/:node`, `/unknown-users` | `/traces`, `/traces/{id}`, `/api/agent/stats*`, `/unknown-users` | Trace waterfall; agent time-series dashboards. |

**New chart types needed by then:**
- **Heatmap** (Phases 1 and 3): an SVG grid with steps of `--accent` opacity, a tooltip and a legend.
- **Stacked percent bar** (request outcomes).
- **Waterfall** (traces).

All must follow `DESIGN.md` §7. Add each one to `components/` the first time a page needs it, not before.

---

## Phase 7 — Cutover (½ day)

**1. Parity check.** Each page listed above must:
- load in Chromium at 1440 light, 1440 dark and 390 light, in both VI and EN;
- show 0 console or page errors and no horizontal overflow;
- work with the main interactions (filters, tabs, paging, selection, links between pages).

Script: `frontend-next/scripts/check_pages.py`, reusing the scratchpad `shot.py` pattern.

**2. Serve the new app.**
- Point FastAPI's static mount (`backend/main.py`: the `frontend/dist` path) at `frontend-next/dist`, ideally through an env var such as `OTEL_UI_DIST` with the old path as the default.
- Keep the SPA fallback for deep links.
- Run `./run_server.sh restart` and check `:31102`.

**3. Update the image.**
- In `deploy/docker/Dockerfile`, make the `ui-builder` stage build `frontend-next`.
- Rebuild and push the image, then run `helm upgrade` (check the ClickHouse/ingest deadlock note in `AGENTS.md` first).
- **This step needs the user's go-ahead.**

**4. Rollback.** Set the env var back to `frontend/dist` and restart.

**5. Retire the old app.** After a week without regressions, delete `frontend/` in its own commit and update `AGENTS.md`.

---

## Rough effort

| Phase | Effort |
|---|---|
| 0 | 1 d |
| 1 | 0.5 d |
| 2 | 2 d |
| 3 | 1.5 d |
| 4 | 2 d |
| 5 | 3–4 d |
| 6 | 1.5 d |
| 7 | 0.5 d |

**Total: about 12–13 working days.** Phase 5 carries the most risk.

## Risks

- **Topology and the Access explorer:** they contain a lot of tuned interaction work. Port the layout code and its behaviour notes from `AGENTS.md`; don't redesign them from scratch.
- **Lost translations:** the old dictionary overrode generic keys. In the new app, write explicit `t(en, vi)` pairs only.
- **Backend quirks the old UI works around:**
  - show completed buckets only;
  - `metrics` summary returns zeros for APIs, so use the series instead;
  - legacy `/apis/{api}/principals` returns nothing in ClickHouse mode.

  Before each phase, check the matching `AGENTS.md` section.
- **Scope creep:** match the old page's behaviour first, and improve it in a later step.

## Optional stopgap (only if a light theme is needed in production before cutover)

1. Fix the old app's broken build: `AccessFlow.tsx` and `AccessMatrix.tsx` import `useTheme` from `../theme`, but it actually lives in `App.tsx`.
2. Copy the `DESIGN.md` token values into its light theme.

This is limited to a day. Do no further work on `frontend/`.
