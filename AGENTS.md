> **Port layout:**
> - Local host dev server: `0.0.0.0:31102` (`tmux session tracescope-31102`, managed via `./run_server.sh`).
> - In-cluster Kubernetes NodePort: `30102` (`tracescope-api` Service, routing directly to `tracescope-app-0`).
> - Trace Ingestion NodePort: `30103` (`tracescope-ingest` OTLP intake).
> - Bootstrap server: `30105`.
> The former NetworkTracing hub on `:31115` is legacy and is not used.
> See [GUIDE.md](file:///home/ubuntu/Viettel/OtelTrace/GUIDE.md) for full generator options, parameter guide, and deployment manual.

# TraceScope Context and State Management (AGENTS.md)

## 60/30/10 color plan (2026-10-02; docs only, not implemented)

- `docs/color-60-30-10-plan.md` (detailed, agent-executable: rules, 5 phases with checkpoints, per-file inventory, decision table, POSIX guard script `frontend/scripts/check-color-budget.sh` (verified: fails on current tree as expected), in-browser pixel-share script, DoD). Current frontend does not meet 60/30/10 (no 30 structure tier: page/surface/sidebar nearly identical; violet accent ~375 uses; amber `--accent-2` second accent; 105 decorative status tints). Plan: add `--structure*` tokens, move rail/top bar/headers/chips to it, cut accent to active/selected/primary/main series, neutral dashed expected lines, grep budget script, pixel-share verification. ~5 days. Open decision: tinted light vs dark rail for the 30 tier.
- Bug found: `var(--text-muted)` (36 uses) and `var(--border-line)` (4) are undefined in `frontend/src`.

## Frontend Complete In-Place Restyle & Legacy Override Cleanup (2026-10-02; docs/frontend-restyle-plan.md COMPLETE)

- **Completed Phases:**
  - **Phase A (Tokens & Theme Plumbing):** Created `frontend/src/styles/tokens.css` with semantic daylight and night CSS variables; rewired `frontend/tailwind.config.js` to reference semantic CSS variables; created `frontend/src/theme.tsx` dynamic provider and inline theme script in `index.html` guaranteeing zero flash on reload and default dark theme preservation.
  - **Phase B (Shared Primitives & App Shell):** Restyled `components.tsx`, `EntityLink.tsx`, `EpisodePrimitives.tsx`, and `App.tsx` navigation sidebar, breadcrumbs, search, and two-option Light/Dark theme switcher.
  - **Phase C (Charts):** Standardized `chartTheme.ts`, `ZoomableDashboardChart.tsx`, and `ChangeVisualEvidence.tsx` reading dynamic CSS variables from `useTheme()` tokens with daylight and night area gradients.
  - **Phase D (Graphs & Topology):** Restyled `accessEncoding.ts`, `Topology.tsx`, `InteractiveTopology.tsx`, `AccessFlow.tsx`, `AccessMatrix.tsx`, `AccessExplorer.tsx`, and `ServiceAccessBoard.tsx` with dynamic state colors and canvas/SVG repainting.
  - **Phase E (Complete Page Sweep):** Swept 100% of pages (`Overview.tsx`, `Services.tsx`, `ApiDetail.tsx`, `user/UserActivityWorkspace.tsx`, `user/UserDirectory.tsx`, `user/UserLayout.tsx`, `user/UserChangesTab.tsx`, `Changes.tsx`, `Alerts.tsx`, `Topology.tsx`, `Behavior.tsx`, `BehaviorGraph.tsx`, `BehaviorAccess.tsx`, `Traces.tsx`, `AgentStats.tsx`, `UnknownUsers.tsx`, `Accounts.tsx`, `Principals.tsx`, `Anomalies.tsx`, `UserIntelligence.tsx`, `i18n.tsx`).
  - **Phase F (Legacy Override Removal & Grep Verification):**
    - Completely stripped 500+ lines of dark hover overrides, ProServe gradient layer, particles, cubes, and `[class~="..."]` hacks from `frontend/src/index.css`.
    - Removed legacy aliases from `src/styles/tokens.css` and `frontend/tailwind.config.js`.
    - Verified all 5 grep checks from §2F Step 4 return **0**:
      1. `grep -rhoE "\-\[#[0-9a-fA-F]{3,8}\]" src | wc -l` -> **0**
      2. `grep -rhoE "(^|[ \"'\`])dark:" src | wc -l` -> **0**
      3. `grep -rhoE "\b(bg|text|border|ring|divide)-(slate|gray|zinc|neutral|stone|blue|sky|indigo|violet|purple|fuchsia|pink|rose|red|orange|amber|yellow|lime|green|emerald|teal|cyan)-[0-9]{2,3}" src | wc -l` -> **0**
      4. `grep -rnE "#[0-9a-fA-F]{6}" src --include=*.ts --include=*.tsx | grep -v "styles/tokens.css" | wc -l` -> **0**
      5. `grep -rn "isLight\|theme === \"light\"\|backdrop-blur\|bg-gradient" src | wc -l` -> **0**
  - **Bundle & API Verification:**
    - Production build compiled cleanly with `tsc -b && vite build`: CSS reduced from 102.3 kB to 42.67 kB (~60% reduction).
    - Tested 12 endpoints on dev server `http://127.0.0.1:31102` (all 200 OK).
  - **State Reference:** Continuously synced with [STATE.md](file:///home/ubuntu/Viettel/OtelTrace/STATE.md).

## Learned graph IP evidence join fix (2026-10-02; image `xhatsu101/tracescope:0.4.7`/`app-0.4.7`/`ingest-0.4.7` pushed multi-arch, chart 0.3.11 prepared; Helm upgrade NOT yet run; not committed)

- **Cause:** `behavior_sources.sql_day()` joined `metric_buckets.operation` (`POST /api/...`) to `topology_principal_ip_5m.api` (`service/POST /api/...`, built from `operation_key`), so 0 of ~20k recent rows matched and the learned graph had no `ip` nodes / `peer_on_call` edges (live `/api/v1/behavior/topology`: 16 service nodes, 0 ip_associations).
- **Fix:** the IP subquery strips the `service/` prefix into `ip_operation` (not named `api`: same-name alias in a join subquery returns wrong values in ClickHouse). Regression test `tests/test_behavior_source_ips.py` (fails without the fix); graph/access/boundary suites 43/43.
- **Activation pending:** the cluster worker (old image) owns `behavior_*` state and would overwrite a host-side replay with IP-less days, so it needs a new image/release. After deploy, older days need `behavior_state.next_day` reset for `legacy_metrics` to re-read them (rebuilds the learned graph). Today's day fills in on its own.
- **Other IP gaps (not fixed):** `traces.ip_resolution` is `unknown` and `effective_client_ip` empty for all rows; in-cluster pod IPs (`10.244.x.x`) are classified `client`; `principal_activity_5m` excludes anonymous principals; ~16% of IP rollup rows have no caller.

## Transparent top bar fix (2026-10-02; frontend only, built into `frontend/dist`, served on `:31102`, not committed)

- **Cause:** the in-progress token-based `frontend/src/index.css` rewrite dropped the `.toolbar` and `.toolbar-control` rules, so the sticky top bar (`FilterBar` in `App.tsx`) had no background and page content showed through; inputs/selects using `toolbar-control` (Alerts, Changes, Behavior access) lost their control styling too.
- **Fix:** re-added both in `@layer components` with the new tokens (`--surface`, `--border`, `--border-strong`, `--surface-2`, `--text`, `--radius-ctl`). Verified in Chromium: solid `#18181b` (dark) / `#ffffff` (light), no page errors. The cluster image (`0.4.7`) was built before this fix and does not include it.

## Complete UI Hover States & Light Mode Font Color Remediation (2026-10-02)

- **Problem & Root Causes Identified:**
  1. **Dark Hover Backgrounds in Light Mode:** Table rows, cards, list items, and tabs used dark mode hover classes (`hover:bg-[#181b1f]`, `hover:bg-[#202226]`, `hover:bg-[#111217]`, `hover:bg-[#292133]`, `hover:bg-[#202436]`) which turned jet-black on hover in light mode.
  2. **Invisible White Text on Hover in Light Mode:** Action buttons, links, and icons with `hover:text-white`, `hover:text-[#fff]`, `hover:text-[#d8d9da]`, `hover:text-[#f1f3f5]` became invisible white text on white/light surfaces when hovered.
  3. **Washed-out Pastel Text in Light Mode:** Pastel colors calibrated for dark backgrounds (`text-[#a9ccff]`, `text-[#8bb8fa]`, `text-[#8db7fa]`, `text-[#9be7d8]`, `text-[#82d5c4]`, `text-[#e3c4f1]`, `text-[#d9b4ea]`, `text-[#ffb45e]`, `text-[#ffb767]`, `text-[#fb7185]`) lacked sufficient contrast on light surfaces (< 3:1).
  4. **Text-white remapping preservation:** Ensuring solid colored background badges (e.g. `btn-primary`, `bg-blue-600`, `bg-violet-600`, `bg-rose-500`) preserve crisp `#ffffff` text while neutral text-white elements remap to dark text on light surfaces.
- **Architectural & Global CSS Fixes (`frontend/src/index.css`):**
  - **Comprehensive Light Mode Dark Hover Remap:**
    Added global rules mapping all dark hover backgrounds (`hover:bg-[#181b1f]`, `hover:bg-[#202226]`, `hover:bg-[#111217]`, `hover:bg-[#1f222b]`, `hover:bg-[#252934]`, `hover:bg-[#1a1d2e]`, `hover:bg-[#202333]`, `hover:bg-[#202436]`, `hover:bg-[#292133]`, `hover:bg-slate-800`, `hover:bg-slate-900`, `hover:bg-gray-800`, `hover:bg-zinc-800`, `hover:bg-white/`) to `background-color: var(--theme-surface-hover) !important` (`#f7f7fa` / `#f1f5f9`).
  - **Comprehensive Light Mode Hover Text Remap:**
    Added rules mapping `hover:text-white`, `hover:text-[#fff]`, `hover:text-[#d8d9da]`, `hover:text-[#f0f3f6]`, `hover:text-[#f1f3f5]`, `hover:text-slate-100`, `hover:text-slate-200`, `group-hover:text-white` to `color: var(--theme-text) !important` (`#172235`).
  - **Accessible Accent Hover Remap:**
    Mapped `hover:text-[#a9ccff]`, `hover:text-[#5794f2]`, `hover:text-cyan-100/200`, `hover:text-indigo-300`, `group-hover:text-indigo-300` to `#1d63dc !important`; `hover:text-[#9be7d8]/[#56b9a8]` to `#0d9488 !important`; `hover:text-[#e3c4f1]/[#b877d9]` to `#7c3aed !important`; `hover:text-[#ff9830]` to `#d97706 !important`.
  - **Pastel Color Contrast Enforcement (WCAG AA >= 4.5:1):**
    Mapped `text-[#a9ccff]`, `text-[#8bb8fa]`, `text-[#8db7fa]` -> `#1d63dc !important`; `text-[#9be7d8]`, `text-[#82d5c4]` -> `#0d9488 !important`; `text-[#e3c4f1]`, `text-[#d9b4ea]` -> `#7c3aed !important`; `text-[#ffb45e]`, `text-[#ffb767]` -> `#d97706 !important`; `text-[#fb7185]`, `text-[#f43f5e]` -> `#dc2626 !important`; `text-[#34d399]` -> `#16a34a !important`; `text-white/` -> `var(--theme-text-secondary) !important`.
  - **Protected Solid Badge Text:**
    Explicitly guarded `.btn-primary`, `.btn-cyan`, `bg-blue-600`, `bg-violet-600`, `bg-indigo-600`, `bg-rose-500`, `bg-rose-600`, `bg-red-600` so their text remains `#ffffff !important`.
  - **Dark Hover Borders Remap:**
    Mapped `hover:border-[#34373b]`, `hover:border-[#7b7d80]`, `hover:border-[#2a2d30]`, `hover:border-[#262838]`, `hover:border-white/` to `border-color: var(--theme-border-strong) !important`.
- **Component-Level Upgrades with Direct Tailwind Light/Dark Variants:**
  - `frontend/src/pages/Overview.tsx`: Table headers now hover `hover:text-[#172235] dark:hover:text-[#d8d9da]`; Top users table rows hover `hover:bg-[#f1f5f9] dark:hover:bg-[#181b1f]`; View all button hovers `hover:text-[#172235] dark:hover:text-white`; Important changes rows hover `hover:bg-[#f1f5f9] dark:hover:bg-[#181b1f]`.
  - `frontend/src/pages/Services.tsx`: View all button hovers `hover:text-[#172235] dark:hover:text-white`; Attention operations hover `hover:bg-[#f1f5f9] dark:hover:bg-[#181b1f]`; Operations table rows hover `hover:bg-[#f1f5f9] dark:hover:bg-[#181b1f]`; Users table rows hover `hover:bg-[#f1f5f9] dark:hover:bg-[#181b1f]`; Representative traces button and rows hover `hover:bg-[#f1f5f9] dark:hover:bg-[#181b1f]`.
  - `frontend/src/pages/ApiDetail.tsx`: Traces action button hovers `hover:text-[#172235] dark:hover:text-white`; Traces table rows hover `hover:bg-[#f1f5f9] dark:hover:bg-[#181b1f]`; PartyTable rows hover `hover:bg-[#f1f5f9] dark:hover:bg-[#181b1f]`.
  - `frontend/src/components/AccessExplorer.tsx`: Segmented control upgraded to `bg-white dark:bg-[#111217]` with `hover:bg-[#f1f5f9] dark:hover:bg-[#202226]` and `hover:text-[#172235] dark:hover:text-white`; search clear button hovers `hover:text-[#172235] dark:hover:text-white`; row items hover `hover:bg-[#f1f5f9] dark:hover:bg-[#181b1f]`; load more button hovers `hover:bg-[#f1f5f9] dark:hover:bg-[#181b1f]`; selection header close button hovers `hover:text-[#172235] dark:hover:text-white`.
  - `frontend/src/components/FleetTriage.tsx`: Scope buttons upgraded with `border-[#1d63dc] dark:border-[#5794f2] text-[#1d63dc] dark:text-[#5794f2]` and inactive hover `hover:text-[#172235] dark:hover:text-[#d8d9da]`; service table rows hover `hover:bg-[#f1f5f9] dark:hover:bg-[#181b1f]`; entity link hovers `hover:text-[#1d63dc] dark:hover:text-[#5794f2]`.
  - `frontend/src/components/ServiceAccessBoard.tsx`: Selected chips upgraded to high-contrast colors (`text-[#1d63dc] dark:text-[#a9ccff]`, `text-[#0d9488] dark:text-[#9be7d8]`, `text-[#7c3aed] dark:text-[#e3c4f1]`) with clear buttons hovering `hover:text-[#172235] dark:hover:text-white`.
  - `frontend/src/components/EpisodePrimitives.tsx`: `SemanticAssessmentBadge` tone colors mapped with `text-[#7c3aed] dark:text-[#d9b4ea]`, `text-[#1d63dc] dark:text-[#8bb8fa]`, `text-[#d97706] dark:text-[#ffb767]`; `entityTokenClass` upgraded to `text-[#7c3aed] dark:text-[#d9b4ea]`, `text-[#1d63dc] dark:text-[#8db7fa]`, `text-[#0d9488] dark:text-[#82d5c4]`; `EpisodeCard` background set to `bg-white dark:bg-[#111217]` and hover to `hover:bg-[#f1f5f9] dark:hover:bg-[#181b1f]`.
  - `frontend/src/components/InvestigationPanel.tsx`: Technical details summary hovers `hover:text-[#172235] dark:hover:text-[#d8d9da]`; `InvestigationEntity` colors mapped with `text-[#1d63dc] dark:text-[#8db7fa]`, `text-[#0d9488] dark:text-[#82d5c4]`, `text-[#7c3aed] dark:text-[#d9b4ea]`.
  - `frontend/src/pages/Changes.tsx`: View scope buttons hover `hover:bg-[#f1f5f9] dark:hover:bg-[#181b1f]`; header strip styled with `bg-[#f8fafc] dark:bg-[#181b1f]`; change episode articles hover `hover:bg-[#f1f5f9] dark:hover:bg-[#181b1f]/60`; action links hover `hover:underline` with high-contrast text.
  - `frontend/src/pages/user/UserLayout.tsx`: Back button styled with `bg-white dark:bg-[#181b1f]` and hover `hover:text-[#172235] dark:hover:text-white`; user switcher rows hover `hover:bg-[#f1f5f9] dark:hover:bg-[#202436] hover:text-[#172235] dark:hover:text-white`; nav tabs styled with `bg-white dark:bg-[#111217]` and hover `hover:bg-[#f1f5f9] dark:hover:bg-[#181b1f] hover:text-[#172235] dark:hover:text-[#d8d9da]`.
  - `frontend/src/pages/user/UserActivityWorkspace.tsx`: Detail tabs hover `hover:text-[#172235] dark:hover:text-white`; traces button hovers `hover:text-[#172235] dark:hover:text-white`; traces rows and party table rows hover `hover:bg-[#f1f5f9] dark:hover:bg-[#181b1f]`; entity labels and icons use calibrated contrast colors.
  - `frontend/src/pages/Topology.tsx`: Edge table rows hover `hover:bg-[#f1f5f9] dark:hover:bg-[#292133]` with readable text `#172235 dark:text-white`.
  - `frontend/src/App.tsx`: Toolbar filter clear buttons hover `hover:text-[#172235] dark:hover:text-[#d8d9da]`.
- **Verification:**
  - `npm run build` completed with zero errors (`dist/assets/index-ComdsnJc.css` 102.29 kB, `dist/assets/index-qxiCudg3.js` 1,867.88 kB).
  - Dev server at `http://127.0.0.1:31102` verified serving fresh bundle with all light mode hover and text rules active.
  - Tested 9 API endpoints returning 200 OK (`/api/v1/health`, `/api/v1/services`, `/api/v1/apis`, `/api/v1/behavior/overview`, `/api/v1/behavior/topology`, `/api/v1/behavior/profiles`, `/api/v1/changes`, `/api/v1/alerts`, `/api/v1/dashboard/series`).

## Dashboard Overview: Removal of Hero Banner ("Live service intelligence") (2026-10-02)

- **Action:** Removed the `proserve-hero` section containing the "Live service intelligence" pill, "Stay ahead of what changes" heading, descriptive copy, and action buttons from `frontend/src/pages/Overview.tsx`.
- **Rationale:** Maximizes above-the-fold operational screen space for core KPI metric cards (TPS, Bandwidth, Needs attention, Observed footprint) and traffic charts.
- **Verification:**
  - `npm run build` compiled cleanly into `dist/assets/index-Casmpc75.js` and `dist/assets/index-BK1YPfSa.css`.
  - Local dev server at `http://127.0.0.1:31102` verified serving bundle without hero banner.
  - Backend API health and endpoints tested (200 OK).

## Reset: `frontend-next/` Clean Removal for Fresh Start (2026-10-02)

- **Action:** Removed `/frontend-next` completely upon user request to start clean from scratch.
- **Preserved Design & Plan References:**
  - `docs/frontend-next-design.md`: Design guide (tokens, typography, layout recipes, chart rules).
  - `docs/frontend-next-migration-plan.md`: Migration plan (phases 0-7, cutover steps, rollback instructions).
- **Process & Port Cleanup:** Stopped Vite preview server on `:31110` (`tmux kill-session -t tracescope-next-31110`).
- **Active System State:** Local dev server running on `:31102` serving existing `frontend/dist`. Clean slate ready for fresh implementation.

## frontend-next design guide and migration plan (2026-10-02; docs only)

- `frontend-next/DESIGN.md`: style guide for agents (tokens, type/spacing, layout, component recipes, chart rules, page checklist, Tailwind porting).
- `docs/frontend-restyle-plan.md` (chosen path): in-place light + dark restyle of `frontend/` (keep components/logic, replace ~2.3k `[#hex]` classes, 584 OS-bound `dark:` variants and the index.css override layer with one token file; phases A tokens, B primitives, C charts, D graph SVG/canvas, E page sweep with codemod, F cleanup greps; ~7 days).
- `frontend-next/MIGRATION_PLAN.md`: replace `frontend/` page by page in `frontend-next` (phase 0 router/i18n/shell, 1 dashboard, 2 services+APIs, 3 users, 4 changes, 5 topology+behavior, 6 traces/agents, 7 cutover via FastAPI dist path with rollback); old app stays live until cutover; ~12-13 days.

## Auto-Collapsing Side Panel (`frontend-next/`) (2026-10-02)

- **Mechanics & Responsiveness:**
  - **Responsive Auto-Collapse (< 1200px):** Automatically switches from wide 240px side panel to a compact 64px icon rail on viewports below 1200px (tablets, split-screen, smaller laptops), maximizing horizontal canvas for charts, tables, and topology.
  - **Mobile Drawer Auto-Collapse (<= 760px):** Auto-collapses completely off-canvas (`transform: translateX(-100%)`). Tapping the Topbar hamburger button (`<Icon name="menu" />`) slides the sidebar out over a frosted backdrop (`.sidebar-backdrop`). Tapping any navigation link, clicking the backdrop, or resizing automatically collapses (closes) the drawer.
  - **Hover / Peek Expansion:** On desktop/tablet, when collapsed to 64px, hovering over the collapsed rail (`.sidebar.collapsed:hover`) smoothly floats and expands the sidebar to 240px with `box-shadow: 4px 0 24px rgba(0,0,0,0.16)` without shifting page layout, allowing full labels to be read. Moving the cursor away **automatically collapses** it back into the compact icon rail.
  - **Manual Pin & Shortcut:** Dedicated toggle buttons (`<Icon name="panelLeftClose" />` / `<Icon name="panelLeftOpen" />`) placed in the Topbar header and Sidebar header allow users to lock the sidebar pinned open or collapsed. Supports keyboard shortcut `Ctrl+B` / `Cmd+B`.
  - **State Persistence:** User preference is stored in `localStorage["ts-sidebar-collapsed"]`.
  - **Collapsed Visual Design:** Grid transitions smoothly (`grid-template-columns: 64px minmax(0, 1fr)`). Brand text, group labels, and item titles are hidden; group labels become subtle 1px dividers; nav icons are centered in 44x38px hitboxes with native hover tooltips; ClickHouse status pill collapses to a centered pulsing green dot.
- **Verification:**
  - `npm run build` compiled cleanly in 2.54s (`dist/assets/index-BT74qhv9.js` and `index-ClPHUC3H.css`).
  - Preview server on `:31110` restarted and serving fresh bundle.
  - Automated tests verified:
    - 1100x800: `collapsed_in_dom=True` (auto-collapsed).
    - 1440x900: `collapsed_in_dom=False` (expanded by default).
    - 390x844: `mobile-menu-toggle` rendered and active.
    - All 17 application routes regression-tested and passing 100%.

## Complete `frontend-next/` Build (DESIGN.md Compliance & Full `/frontend` Layout + Info Parity) (2026-10-02)

- **Architecture:** Complete full-suite TraceScope console built from scratch in `frontend-next/` strictly adhering to `frontend-next/DESIGN.md`: React 19 + Vite 7 + TypeScript, zero external CSS/chart/router libraries, Inter typography, 100% token-based CSS in `tokens.css` with seamless daylight-first and dark mode parity, and double-frame `.card` > `.inner` layout.
- **Layout & Information Parity with `/frontend`:**
  - **SideNav:** 4 operational groups matching `/frontend`: `Dashboard`, `Explore` (Services, APIs, Users, Topology, Learned behavior), `Changes` (Changes, Alerts), and `Investigate` (Traces, Agent fleet). Bottom ClickHouse connection indicator pill (`● ClickHouse · connected`) with pulsing green dot.
  - **Topbar & Global Filters:** Topbar with breadcrumb trail, global search input, operational window pill (`Current: 5m · History: 7d`), refresh button with spinner, collapsible filters drawer button (with active filter badge), bilingual language switcher (EN/VI), theme switcher (Daylight/Dark), timezone selector (`Browser Local`, `UTC`, `Asia/Ho_Chi_Minh`), and live connection badge. Expandable global filter drawer with dropdowns for Environment, Group, Module, Service, Operation, Account, Comparison Window, and "Clear Filters".
  - **Overview Page:** 4 StatCards with pure SVG area-gradient Sparklines matching old `/frontend` (TPS avg/peak with sparkline, Bandwidth with sparkline, Needs attention with sparkline, Observed footprint split Service/User buttons; hero banner permanently removed per user request), Total TPS vs Expected line chart with HTTP 4xx/5xx error rate, **Top Users (2/5) with interactive column sorting (`TPS`, `Services`, `APIs`, `Changes`) + 7x24 Activity Matrix Heatmap (3/5)**, and Access Explorer / Relationships view.
  - **Services & APIs:** Service catalog and API catalog with method badges, priority/error sorting, and detail views mirroring `/frontend` (5 KPI cards with sparklines, TPS vs Expected 3/5, Recent Changes 2/5, Neighbors inspector, tabbed sub-tables for Operations, Callers, Dependencies, Users).
  - **Users:** Identity catalog with reach counts; user detail page with TPS chart, recent changes, reach breakdown, and tabs for Reached Services, APIs, Callers, Client IPs.
  - **Interactive Topology:** Pure SVG service graph with caller/service column positioning, smooth bezier curved arrows with traffic-weighted stroke, live search, and flow drawer.
  - **Changes & Alerts:** Behavior change triage table with box-free left-aligned priority badges, 1h visual evidence time-series chart around incident pivot; alert policies catalog (`/alerts`) with dispatch delivery table.
  - **Learned Behavior (`/behavior`):** Interaction graph, learned baseline profiles (`/api/v1/behavior/profiles`), and engine coverage.
  - **Traces:** Distributed trace streams with service filter and HTTP status badges; trace waterfall timeline with depth-indented hierarchy and span attribute code inspector.
  - **Agents & System:** eBPF / OBI Node Health metrics (`/agents`), Runtime Configuration (`/settings`), and TraceScope Platform guide (`/help`).
- **Verification:**
  - `npm run build` completed cleanly (`tsc -b && vite build` -> `dist/assets/index-B-AZlAnL.js` and `index-B7sDig2T.css`).
  - Preview server running on `:31110` with `/api` proxying to backend dev server on `:31102`.
  - All 17 routes tested and confirmed passing with headless Chromium: `#//`, `#/services`, `#/services/:service`, `#/apis`, `#/users`, `#/users/:principal`, `#/topology`, `#/behavior`, `#/changes`, `#/alerts`, `#/traces`, `#/agents`, `#/settings`, `#/help`.
  - Permanent removal of hero banner ("Stay ahead of what changes", "Live service intelligence", etc.) confirmed via headless DOM inspection.
  - Verified SVG sparkline rendering with gradient area fills across KPI cards.
  - Responsive layout verified across all 4 target viewports (1440x900, 1100x800, 760x600, 390x844).
  - Backend API health and proxy verified 200 OK across `/health`, `/services`, `/apis`, `/behavior/overview`, `/behavior/topology`, `/behavior/profiles`, `/alerts`, `/dashboard/series`.

## Complete Light Mode Deep Redesign (Daylight Operational Console) (2026-10-02; frontend rebuilt, local :31102 restarted)

- **Architectural Shift:** Removed destructive wildcard CSS overrides (`html[data-theme="light"] [class*="text-[#"]`) in `frontend/src/index.css` that previously crushed all status pills, error badges, metrics, and entity highlights into monochrome black.
- **Semantic Token Architecture:**
  - `frontend/src/theme.ts`: Added typed token definitions (`ColorTokens`, `DARK_THEME`, `LIGHT_THEME`, `getThemeTokens`) defining low-glare canvas (`#f3f6fa`), clean daylight surfaces (`#ffffff`, `#f8fafc`, `#edf2f7`), accessible dark text (`#172235`, `#334155`, `#475569`, `#64748b`), and WCAG AA compliant operational status colors (`#1d63dc`, `#16a34a`, `#d97706`, `#dc2626`, `#7c3aed`, `#0d9488`).
  - `frontend/src/chartTheme.ts`: Standardized chart tokens for ECharts and Recharts (tooltips, axes, grids).
  - `frontend/src/accessEncoding.ts`: Added `getStateStyle(state, isLight)` and `getEntityColor(kind, isLight)` providing calibrated SVG strokes and fills for access flows, matrices, and topologies.
  - `frontend/tailwind.config.js`: Integrated semantic CSS variable mappings for `canvas`, `sidebar`, `surface`, `line`, `ink`, `status`, and `entity`.
  - `frontend/src/index.css`: Rebuilt root and daylight variable tokens with purposeful surface contrast; mapped dark utility literals safely without crushing semantic text colors; added daylight forms, inputs, tooltips, and scrollbars.
- **Component Upgrades:**
  - **Shell:** SideNav brand mark with vibrant blue fill, active states with `bg-blue-50/90 border-blue-200 text-[#172235]`, readable slate inactive navigation, and green ClickHouse status pill. Toolbar with high-contrast breadcrumbs, time-range badge, and theme switcher (Sun/Moon).
  - **Primitives (`components.tsx`):** `Page`, `Panel`, `MetricCard`, `InteractiveMetricCard`, `TpsLineChart`, `Loading`, `ErrorState`, and `chartTooltip` styled with daylight borders (`#d5dee9`), deep ink headings, and high-contrast status metrics.
  - **Charts (`ZoomableDashboardChart.tsx` & `ChangeVisualEvidence.tsx`):** Theme-aware ECharts instance with daylight palette, white tooltip, light zoom slider, and 1h before/after comparison metric boxes.
  - **Access & Behavior (`AccessFlow.tsx`, `AccessMatrix.tsx`):** Dynamic ribbon states and entity colors (`getEntityColor`, `getStateStyle`), daylight filter bars, search controls, inspector readouts, and table views.
  - **Interactive Topology (`InteractiveTopology.tsx`):** Node card backgrounds (`bg-white dark:bg-[#11131b]/95`), border colors, entity tones, SVG arrow markers, search results dropdown, zoom controls, and flow drawer.
- **Verification:**
  - `npm run build` completed with zero TypeScript/bundling errors (`dist/assets/index-D61VQ0w0.js`, `dist/assets/index-Cpo8qVn9.css`).
  - Local server on `:31102` restarted via `./run_server.sh restart`.
  - Verified 200 OK responses across API endpoints (`/api/v1/health`, `/api/v1/services`, `/api/v1/apis`, `/api/v1/behavior/overview`, `/api/v1/behavior/topology`, `/api/v1/dashboard/series`).
  - Dark mode remains 100% intact and visually identical.

## User detail page in the Service/API layout (2026-10-02; backend live on `:31102`, frontend NOT served yet, not committed)

- **Backend (live after `./run_server.sh restart`):** `project_lists` gained a `service` column (`LIST_COLUMNS = caller, credential, service, api`) and `scope='credential'` (`/api/v1/behavior/access?view=lists&scope=credential&credential=<user>`; 422 without a credential). Credential scope spans every Service; `service` becomes an ordinary column filter (`q_service`, `service_offset`, `select_type=service`); the selection is limited to that user's relationships and its sides are credential -> (caller | service), service -> (caller | api), caller -> (service | api), api -> (caller | service). Service scope is unchanged (a `service` column filter is ignored). Tests: 3 new in `tests/test_behavior_access_lists.py`; access + lists + boundary suites 26/26.
- **Frontend:** `AccessExplorer` has `lockedCredential` (columns Caller | Service | API, the user's own Sent by / Services it reaches diagram as default, API labels lose the Service prefix once a Service is chosen, `splitApiLabel` for API links); `/users/:principal/activity` is one scroll like Service/API detail: KPI cards + TPS vs expected with the shared `RecentChangesPanel` beside it, Request outcomes + active-hour heatmap row, `Access for {user}` explorer, tabs Services / APIs / Caller services / Source IPs / Traces (from `/topology/principals/{p}/ips`, APIs spelled `service/operation`, TPS = requests / window; 15-row pages). The Behavior | Access segmented toggle and the old IP -> Service -> API board were removed.
- **Not served:** `frontend/dist` still holds the previous bundle. The working tree has an unfinished theme refactor from another source (`src/theme.ts`; `AccessFlow.tsx` and `AccessMatrix.tsx` import `useTheme` from `../theme`, which does not export it; it lives in `App.tsx`), so `npm run build` fails. Verified instead with a scratch copy that imports `useTheme` from `../App` (full `tsc` clean): Chromium (VI) on `alice_wsse` at 1440/390 px, 3 callers / 3 Services / 19 APIs, Service click narrows to 7 APIs, tabs 3/19/3/8/10, API row navigates to API detail, no overflow or page errors; API and Service pages regression-checked. Run `npm run build` once the theme refactor compiles.

## APIs section: catalog + Service-style API detail (2026-10-02; backend + frontend, local `:31102` restarted, not committed)

- **Sidebar:** new `APIs` entry (`/apis`) between Services and Users. API detail stays at `/services/:name/apis/:api` (`entityPath` unchanged) but highlights `APIs`, not `Services`, in the rail (`navActive` in `App.tsx`; router `aria-current` still marks Services).
- **Backend:** `GET /api/v1/apis` (`backend/app/api/services.py::list_apis`, params `from`/`to`/`q`/`service`/`limit` <=5000) reads `metric_buckets FINAL` (60 s) only: per (Service, operation) requests, errors, error rate, max P95, distinct callers, distinct non-anonymous principals, first/last seen, avg TPS, and `anomaly_status` from open `anomaly_events` matched on target_service + operation.
- **`/apis` catalog** (`pages/ApiDetail.tsx::ApisPage`): summary strip (APIs, Services, open anomalies, with errors), directory with scope tabs, path/Service search, owning-Service select, sort (priority/errors/requests/P95/users/A-Z), 15-row pages, loads up to 2000.
- **API detail** (`ApiDetailPage`) now mirrors Service detail: exported `ServicePerformancePanel` (5 clickable KPI cards + TPS vs expected with overlay; series from `/dashboard/series?service&operation`, which returns `{items}`; bandwidth from `/topology/apis/{api}/metrics` series because its `metrics` summary returns zeros) with the shared `RecentChangesPanel` beside it; `Access for {api}` uses `AccessExplorer lockedApi="service → op"` (API column hidden, Caller | User lists, the API's own Called by / Users used diagram as default selection, no close/self link); tabs Users / Caller services / Traces. Users and Callers come from `/topology/services/{svc}/ips` (rows spell APIs `service/operation`), paged up to 20x500, grouped per principal/caller; anonymous principals are excluded from Users. The legacy `/apis/{api}/principals` and `/api-connections` endpoints return nothing in ClickHouse mode and are no longer used by this page.
- **Validation:** lint/build/diff check pass; `test_api_read_model_boundary.py` 6/6; live `/api/v1/apis` 95 APIs / 11 Services; Chromium (VI) on `order-service POST /api/v1/orders/process` at 1440/390 px: 2 explorer columns, 3 callers / 13 users, user click re-centres and close returns to the API, Users 13 / Callers 3 / Traces 10, no overflow or page errors. Cluster `:30102` image not updated.

## Standalone OBI Agent Only Deployment (Omitting OpenTelemetry Collector) (2026-10-02)

- **Requirements & Design:**
  - Support deploying exclusively the eBPF auto-instrumentation agent (`tracescope-obi` DaemonSet + RBAC + ConfigMap) without deploying the OpenTelemetry Collector (`Deployment`, `Service`, `collector-configmap`).
  - Required when an environment already hosts an OpenTelemetry Collector or routes traces directly to an external OTLP receiver.
  - Critical constraint: when `collector.enabled: false`, OBI's `otel_traces_export.endpoint` must be explicitly configured with the destination OTLP address (e.g. `http://<collector>:4317` or HTTP endpoint).
- **Changes Applied:**
  - `deploy/helm/render-stack.sh`:
    - Added `--no-collector` flag to set `collector.enabled: false`.
    - Added `--export-endpoint <URL>` to supply `obi.export.endpoint`.
    - Added validation to prevent generation without an explicit export endpoint when `--no-collector` is used.
    - Updated stack rendering so ClickHouse mode does not mandate a local in-chart collector.
  - `GUIDE.md`:
    - Documented flags `--no-collector` and `--export-endpoint <URL>` in parameter reference.
    - Added dedicated subsection detailing the 4 resources to apply vs 3 to omit, with CLI commands and YAML generation examples.
    - Saved standalone manifest to `stack-out/tracescope-obi-agent-only.yaml`.
- **Verification:**
  - Tested `./deploy/helm/render-stack.sh --mode clickhouse --no-collector --export-endpoint "http://my-collector:4317" --render` producing clean manifest without Collector Deployment/Service.
  - Verified `helm template` outputs only `ServiceAccount`, `ConfigMap`, `ClusterRole`, `ClusterRoleBinding`, and `DaemonSet`.

## Dashboard Page Layout: Top Users (2/5) and Heatmap (3/5) Row with Column Sorting (2026-10-01)

- **Requirements & Design:**
  - Move the "Top users" card into the same row as the "When behavior changes" Heatmap card on the Dashboard overview (`frontend/src/pages/Overview.tsx`).
  - Arrange in a responsive 2/5 - 3/5 grid: "Top users" on the left (`lg:col-span-2`), "Heatmap" on the right (`lg:col-span-3`).
  - Add interactive column sorting to the "Top users" table for columns: `TPS`, `Services`, `APIs`, and `Changes`.
  - Column headers toggle sort direction between descending and ascending, with visual indicator icons (`ArrowDown`, `ArrowUp`, `ArrowUpDown`) and active column highlighting (`text-[#5794f2] font-semibold`).
  - Query limit expanded to 50 users (`usersDirectoryQuery`) to allow client-side sorting across active users in the selected window.
- **Changes Applied:**
  - `frontend/src/pages/Overview.tsx`:
    - Imported `ArrowDown`, `ArrowUp`, `ArrowUpDown` from `lucide-react`.
    - Added sort state: `userSortField: "tps" | "services" | "apis" | "changes"` (default `"tps"`) and `userSortDir: "asc" | "desc"` (default `"desc"`).
    - Added `handleUserSort` callback and `sortedUserHotspots` / `sortedChangedUsers` compute blocks.
    - Grouped Top users and Heatmap in `<div className="mt-3 grid grid-cols-1 lg:grid-cols-5 gap-3 items-stretch">`.
    - Rendered sortable headers with click handlers on `TPS`, `Services`, `APIs`, `Changes`.
    - Removed redundant separate `Top users` card block from the bottom of the page.
- **Verification:**
  - Built frontend with `npm run build` -> `dist/assets/index-CpxF53g6.js`.
  - Synced bundle to cluster container mount (`/var/lib/kubelet/pods/f92443a6-cdd1-40e8-bfa0-3fa461373e7f/volumes/kubernetes.io~empty-dir/tmp/dist/`).
  - Restarted local server on `:31102` (`./run_server.sh restart`).
  - Both `http://127.0.0.1:31102` and cluster NodePort `http://127.0.0.1:30102` verified returning 200 OK and serving `index-CpxF53g6.js`.

## Changes Page Priority & Review Status: Left-Aligned, Box-Free Badges & Non-Filling Divider Line (2026-10-01)

- **Requirements & Design:**
  - Left-align text and icons for both Priority and Review Status in the first column of the Changes list table (`frontend/src/pages/Changes.tsx`).
  - Eliminate bounding boxes/cards (remove borders and background fills) for both `EpisodeStatusBadge` and `EpisodeWorkflowBadge` (`frontend/src/components/EpisodePrimitives.tsx`), rendering clean colored typography and icons.
  - Drop the "Review status:" prefix from `EpisodeWorkflowBadge`, rendering solely the review state (`Open`, `Monitoring`, `Resolved`) with its icon.
  - Separate the Priority/Status column from the change name column using a subtle vertical dividing line (`w-px bg-[#303236]`) that does NOT fill vertically (`top-2.5 bottom-2.5` inset).
- **Changes Applied:**
  - `frontend/src/components/EpisodePrimitives.tsx`:
    - Added `episodeStatusTone(state)` returning crisp text colors (`text-[#f2495c]`, `text-[#ff9830]`, `text-[#73bf69]`, `text-[#b877d9]`, `text-[#5794f2]`).
    - Updated `EpisodeStatusBadge`: renders `inline-flex items-center justify-start gap-1.5 text-[10px] font-bold uppercase tracking-wider whitespace-nowrap` without box/border by default (optional `box` prop preserved).
    - Updated `EpisodeWorkflowBadge`: renders `inline-flex items-center justify-start gap-1 text-[10px] font-semibold uppercase tracking-wider whitespace-nowrap` showing `{label}` without the "Review status:" prefix.
  - `frontend/src/pages/Changes.tsx`:
    - Left-aligned table column header: `<span>{t("Priority", "Mức ưu tiên")}</span>`.
    - Left-aligned column content: `<div className="relative flex flex-wrap items-start justify-start gap-1 text-left xl:flex-col xl:items-start xl:justify-start">`.
    - Maintained partial vertical divider: `<div className="hidden xl:block absolute -right-1.5 top-2.5 bottom-2.5 w-px bg-[#303236]" />` placed in the center of the column gap and inset top/bottom.
- **Verification:**
  - Built frontend (`npm run build` -> `dist/assets/index-CN0_pA-3.js`).
  - Synced bundle to cluster NodePort (`30102`) and restarted local dev server (`31102`). Both return 200 OK.

## Change in Context Visual Evidence & 1h Before/After Accurate Metrics (2026-10-01)

- **Root Causes of Broken / Contradictory "Change in context" Card (`ChangeVisualEvidence.tsx`):**
  1. **5-Minute Signal vs 1-Hour Chart Rate Discrepancy:** The two top summary boxes previously fetched `detectorHighlight.before` and `detectorHighlight.after`. In novelty/edge detectors (e.g. `new_service_edge`), `after` held the raw 5-minute request count (e.g. 16.0), which was formatted as `16.00 TPS`, directly contradicting the line chart below which plotted true request rates (e.g. `0.05 TPS`).
  2. **Sparse Telemetry & Inaccurate Averages:** Because ClickHouse `metric_buckets` only contains rows for active minutes, sparse telemetry caused Recharts to connect distant points diagonally across the hour or show empty data. `mean(beforePoints)` then either inflated average TPS by averaging only active minutes or displayed "No observed samples".
  3. **Missing `caller` Filtering:** `dashboard/series` supported `service`, `operation`, and `account`, but ignored `caller` (`caller_service` in `metric_buckets`). An edge anomaly for `caller -> service` displayed the aggregate service's metrics rather than the edge.
  4. **Baseline Dimension Key Mismatch:** When `service` was present, `repository.py` defaulted to the whole service's baseline, ignoring specific `principal_target` or `caller_target` baselines.
- **Fixes Applied:**
  - **Dense 1-Minute Bucketing:** `ChangeVisualEvidence.tsx` now builds continuous 1-minute buckets between `startMinute` and `endMinute`. For TPS and HTTP 5xx rate, unrecorded minutes default to 0. For P95 latency, unrecorded minutes default to `null` and are not connected.
  - **True 1-Hour Window Means:** Top boxes now display `1h Before (avg)` and `After Signal (avg)` computed from `mean(beforePoints)` and `mean(afterPoints)`, ensuring exact arithmetic consistency with the chart.
  - **Caller & Edge Filtering:** Added `caller` to `QueryFilters` (`backend/models.py`), `filters_model` / `filter_dict` (`backend/app/application.py`), and `dashboard_series` (`backend/repository.py`). Prioritized baseline lookup specificity: `(account, service) -> (caller, service) -> (service, operation) -> account -> operation -> service -> system-wide`.
  - **Time Window Safety:** Capped `pivot` at `nowMs` to eliminate invalid future projection from window-end timestamps.
- **Verification:**
  - Tested `/api/v1/dashboard/series` with caller/service filters on `:31102` (`caller=traffic-ui&service=order-service` -> 120 points, baseline 0.1033).
  - Built frontend (`npm run build`) and synced dist to both local dev server (`:31102`) and cluster NodePort (`:30102`). Both return 200 OK for `assets/index-DJ7t1p_v.js`.

## Service Detail Page Layout: TPS (3/5) and Recent Changes (2/5) Row (2026-10-01)

- **Unified 60/40 Grid Row on `/services/:serviceName`:**
  - Placed the TPS performance chart and Recent Changes card in a responsive side-by-side grid (`grid grid-cols-1 lg:grid-cols-5 gap-4 items-stretch`).
  - Allocated 3/5 width (`lg:col-span-3`) to the TPS vs Expected chart panel and 2/5 width (`lg:col-span-2`) to the Recent Changes panel.
  - Aligned card heights with `h-full flex flex-col` and scrollable items (`max-h-[262px] overflow-y-auto`).
  - Compiled and deployed bundle to both local dev server (`:31102`) and cluster NodePort (`:30102`).

## ClusterRole Cross-Namespace Tracing & ClickHouse Learning Stack (2026-10-01)

- **Cluster-Wide RBAC (`ClusterRole` & `ClusterRoleBinding`):**
  - Generated manifest includes `ClusterRole` and `ClusterRoleBinding` for `tracescope-obi` ServiceAccount.
  - Grants `get, list, watch` on `pods`, `services`, `nodes`, `namespaces`, `deployments`, `daemonsets`, `statefulsets`, `replicasets` across the entire cluster.
  - Enables OBI to discover, instrument, and trace workloads in any target namespace—including restricted namespaces that regular tenant accounts cannot directly access, but the administrative account applying the YAML can authorize.
- **ClickHouse Mode & Always-On Behavior Learning:**
  - Rendered via `./deploy/helm/render-stack.sh --mode clickhouse --single-yaml ./stack-out/tracescope-all.yaml`.
  - Configures `OTEL_BEHAVIOR_LEARNING_ENABLED: "true"`, `storage.pipelineMode: clickhouse`, `ingest.enabled: true`, and OBI collector exporting directly to `tracescope-ingest:30103`.
  - Manifests output to `stack-out/tracescope-all.yaml` (combined), `stack-out/tracescope.yaml`, and `stack-out/tracescope-obi.yaml`.
- **Live Cluster Deployment & Verification (Authorized kubectl execution):**
  - Applied `./stack-out/tracescope-all.yaml` directly to cluster context `kubernetes-admin@kubernetes`.
  - All resources confirmed healthy: `tracescope-app-0` (2/2 Running), `tracescope-clickhouse-0` (1/1 Running), `tracescope-ingest` (1/1 Running), `tracescope-obi` (DaemonSet 2/2 Running across nodes), `tracescope-obi-collector` (1/1 Running).
  - Ingestion stream verified: OBI Collector exporting batches to `tracescope-ingest:30103` (`POST /v1/traces 200 OK`).
  - Analytics verified: Background worker stage `learned_behavior` completed successfully in shadow mode with 280 profiles.
  - Endpoints confirmed 200 OK: NodePort `http://127.0.0.1:30102/api/v1/health` and Public Ingress `https://trace.n2d.id.vn/api/v1/behavior/overview`, `/topology`, `/access`.

## Multi-Arch Images, Ephemeral ClickHouse (--no-pvc) & Single-YAML Stack (2026-10-01)

- **ClickHouse Without PVC (Ephemeral / Test Environments):**
  - Updated `deploy/helm/tracescope/templates/clickhouse-statefulset.yaml`: supports `.Values.clickhouse.persistence.enabled: false`. When disabled, ClickHouse mounts `emptyDir: {}` instead of a PVC claim.
  - Updated `deploy/helm/render-stack.sh`: added `--no-pvc` flag which renders `clickhouse.persistence.enabled: false` and eliminates the `PersistentVolumeClaim` document from generated manifests.
  - Manual YAML fallback: In any rendered manifest, delete the `kind: PersistentVolumeClaim` named `tracescope-clickhouse-data` and change the StatefulSet `volumes.data` from `persistentVolumeClaim: {claimName: tracescope-clickhouse-data}` to `emptyDir: {}`.
  - Behavior: ClickHouse runs fully in-memory/pod-disk; data resets when the pod restarts. Ideal for quick dev/test environments without dynamic PVC provisioners.
- **Multi-Arch Docker Images & Dedicated AMD64 Tags:**
  - Built and pushed multi-arch manifest lists to Docker Hub (`linux/amd64` + `linux/arm64`):
    - `xhatsu101/tracescope:0.4.6`, `app-0.4.6`, `latest`
    - `xhatsu101/tracescope:ingest-0.4.6`, `ingest-latest`
  - Also pushed dedicated single-arch AMD64 tags to prevent stale ARM64 node cache collisions (`exec format error`):
    - `xhatsu101/tracescope:0.4.6-amd64` (digest `sha256:f63103f0eb6fdf731ae5c95299503bce8a7c21e8ee6a119d460fdcb16d80687d`)
    - `xhatsu101/tracescope:ingest-0.4.6-amd64` (digest `sha256:92091bb62ccc96b76f87653775ff56bbac33fc60fe679cbb8a210653a93ae388`)
- **Generator Flags (`--tag` & `--pull-policy`):**
  - Updated `deploy/helm/render-stack.sh`: supports `--tag <TAG>` (e.g. `--tag 0.4.6-amd64`) and `--pull-policy <POLICY>` (e.g. `--pull-policy Always`).
  - Restructured YAML emission to merge `app:` and `ingest:` sections without duplicate YAML keys.
- **Single-YAML Stack & Namespace Isolation:**
  - `render-stack.sh -n <namespace> --single-yaml [file]`: Bundles full TraceScope application + OBI stack into a single unified manifest with unified namespace injection across all resources.
  - RBAC handling: `--no-cluster-rbac` drops `ClusterRole` & `ClusterRoleBinding` (scoped to namespace `Role`), while `--no-rbac` removes all RBAC resources for clusters with restricted permissions.
  - Full guide and command references maintained in `GUIDE.md`.

## NodePort & Local Port Layout (2026-10-01)

- **Port Disambiguation:**
  - Cluster `tracescope-api` runs on NodePort `30102` (`https://trace.n2d.id.vn` and `http://<node-ip>:30102`).
  - Local development server runs on `http://0.0.0.0:31102` via `OTEL_PORT=31102` in `.env` and `SERVER_PORT` in `run_server.sh`.
  - Both operate concurrently without socket/iptables collision.
- **Ingress Bypass & Direct NodePort Access:**
  - `tracescope-api` (UI & REST API): Port 30102. `templates/api-service.yaml` now supports `type: {{ (default dict .Values.app.service).type | default "ClusterIP" }}` and `nodePort: {{ .Values.app.service.nodePort }}`.
  - `tracescope-ingest` (OTLP Trace Intake): Port 30103. Supports `ingest.service.type: NodePort` and `nodePort: 30103`.
  - `tracescope-obi-collector` (Optional external OTLP receiver): `templates/collector-service.yaml` supports `collector.service.type: NodePort` with `nodePortGrpc` (4317) and `nodePortHttp` (4318).
  - Generator support: `render-stack.sh --nodeport` automatically generates values with `ingress.enabled: false`, `app.service.type: NodePort` (30102), and `ingest.service.type: NodePort` (30103).
  - Generator flags `-n, --namespace <NS>` and `--single-yaml [FILE]`: Added unified namespace parameter and automatic bundling of app + OBI into `tracescope-all.yaml`. All chart templates now inject `metadata.namespace: {{ .Release.Namespace }}`.

## Behavior Learning Activation & Root Cause Resolution (2026-10-01)

- **Root Cause of Behavior Learning Not Working:** In `deploy/helm/tracescope/values.yaml`, `behavior.enabled` defaulted to `false`. This rendered `OTEL_BEHAVIOR_LEARNING_ENABLED: "false"` into the `tracescope-config` ConfigMap. Inside `backend/app/services/behavior_worker.py:126`, `run_behavior_learning()` immediately short-circuited with `{'status': 'disabled'}`. As a result, the worker never analyzed completed windows, never updated `behavior_state`, and `/api/v1/behavior/topology` returned 0 nodes/edges.
- **Fix Applied:**
  - Updated `deploy/helm/tracescope/values.yaml` to set `behavior.enabled: true`.
  - Updated `deploy/helm/render-stack.sh` to include `behavior.enabled: true` in generated TraceScope values.
  - Re-rendered manifests via `render-stack.sh --mode clickhouse --render` and applied updated ConfigMap to namespace `tracescope`.
  - Restarted `tracescope-app` StatefulSet.
- **Verification:**
  - Cluster worker logs show: `{"event": "worker_stage_complete", "stage": "learned_behavior", "elapsed_seconds": 0.356, ... "learned_behavior": {"status": "shadow", "sources": {"legacy_metrics": {"status": "live", "profiles": 49, "deviations": 0}}}}`.
  - Live endpoints on `https://trace.n2d.id.vn`:
    - `/api/v1/behavior/overview`: `mode: shadow`, `enabled: true`, `profile_count: 49`, `requests: 64839`.
    - `/api/v1/behavior/topology`: returns 52 entities and 9 edges.
    - `/api/v1/behavior/access`: returns 15 nodes, 28 links for service focus (`order-service`).

## Direct OTLP (clickhouse mode) caller resolution (2026-10-01; deployed as image 0.4.5, chart 0.3.9, release rev 3)

- `backend/app/services/otlp_parser.py`: canonical `METHOD /path/{id}` operations, request/response bytes from `http.{request,response}.body.size` (and the collector's mirrored spellings; unmeasured stays NULL), and client spans name their peer from `server.address`/`url.full` (cluster DNS -> service, bare host -> service, other FQDN/IP kept whole) instead of `unknown-downstream`. Client spans record `client_span`, servers with `peer.service` record `header`.
- New `backend/app/services/trace_edge_resolution.py` + migration `018_trace_edge_resolutions.sql` (2-day TTL): before each `_aggregate_slice`, stored OTLP rows (+/-61 s context) go through `trace_edges.resolve` and the outcome is written to `trace_edge_resolutions`. Aggregation (`metric_buckets`, `metric_buckets_agg`), service/principal edges and the interactive topology rollups read `traces` through `traces_source_sql()`, which overlays callers/targets and drops paired root clients, non-root clients and internal spans. Raw `traces` rows are never modified; `delete_window` clears the slice first when callers were resolved so a changed caller cannot double count.
- Gate: `OTEL_TRACE_EDGE_RESOLUTION=auto|true|false` (`auto` = on when `OTEL_TRACE_PIPELINE_MODE=clickhouse`), `OTEL_TRACE_EDGE_SKEW_MS`, `OTEL_SERVICE_IP_MAP`; Helm `storage.traceEdge.*`. `elk_to_clickhouse` behavior is unchanged. Agent rows (`is_agent_trace=1`) are never touched.
- Limits: none of the user-behavior readers touch raw `traces` any more (see the trace-free user behavior section below); they read caller-resolved `principal_activity_5m`. Mid-request outgoing client spans now become `client_exit` dependency edges (confidence 0.7), see below.
- ClickHouse gotcha found: an alias equal to its own argument inside a join subquery (`argMax(skip, t) AS skip`) returns the wrong value, so the overlay uses `res_*` names.
- `IngestWriter._TRACE_COLUMNS` (the live /v1/traces writer) previously never persisted `request_bytes`, `response_bytes`, `observed_ip`, `effective_client_ip`, `ip_resolution`, `client_identity_quality`, `context_quality`, `traffic_class`, `is_agent_trace`, so bytes were always 0 in every pipeline using the coalescing writer. Fixed in 0.4.5; regression test `test_high_throughput_writer_persists_bytes_and_ip_evidence`.
- Deploy: `xhatsu101/tracescope:0.4.4` (resolution) then `0.4.5` (writer columns) pushed; `reset_derived()` was run once after 0.4.4. Live check after 0.4.5: ~94% of OTLP rows carry request/response bytes and observed IP.
- Upgrade gotcha: a chart upgrade can reschedule ClickHouse while the ingest rollout surges pods onto the same node; with ~2 CPU per node the ClickHouse pod stays Pending (Insufficient cpu) and ingest never becomes ready (deadlock). Recovery used: scale `tracescope-ingest` to 0 (HPA ignores replicas=0), wait for ClickHouse/app Ready, scale back to 3.
- Tests: `tests/test_otlp_trace_edge_resolution.py` 23/23 (real ClickHouse test DB). Full suite on the working tree: only failures also present with the three modified files at `HEAD` (see below). Test hygiene: tests/conftest.py drops every `test_*` database when any pytest session ends, so never run two pytest sessions concurrently against the same ClickHouse.

## Trace-free user behavior and mid-request dependency edges (2026-10-01; deployed as image 0.4.6, chart 0.3.10, release rev 5; host worker intentionally disabled)

- **Rollup `principal_activity_5m`** (migration 019, ReplacingMergeTree, 35-day TTL; ledger `principal_activity_consumed`): per (5-minute bucket, row_key) credential activity: principal, caller, source IP, target, operation, requests/errors/auth failures/successes, first/last seen, 3 sample trace IDs. `backend/app/services/principal_activity.py::materialize_principal_activity` rewrites whole buckets (DELETE then INSERT) from `traces_source_sql()` in `_aggregate_slice` right after caller resolution, so behavior carries the same resolved callers/targets as `metric_buckets`. A window with no raw traces is skipped, so expired windows keep their rollup rows.
- **No raw trace reads for behavior:** `principal_relationships.py` (rewritten), `behavioral_engine.py` (readiness uses the ingest-time `principal_readiness_summary` MV; detectors read the rollup), `anomaly_detection.py` Detector 9 (user/IP) and `prometheus_metrics.py` (totals from `metric_buckets`, nodes = services) no longer query `traces`. Enforced by `tests/test_api_read_model_boundary.py::test_user_behavior_services_read_the_activity_rollup_not_raw_traces`. Raw `traces` is read only by ingestion, `trace_edge_resolution`, `principal_activity` and Trace Explorer.
- **Incremental processing:** cursor `(updated_at_ms, bucket_start_ms, row_key)`; each cycle rewinds `CURSOR_OVERLAP_MS` (5 s, 0 disables) so a rewrite landing behind the cursor is still seen. The ledger stores the elementwise max already counted; only the positive difference is processed, so re-aggregating a slice never double counts. The ledger is written last in `flush()`. Legacy checkpoints (no `updated_at_ms`) mark everything consumed on first run. Bootstrap (no checkpoint, or <=5 baselines with >100 named requests) is built entirely on the rollup and ends by marking all consumed.
- **Caveats:** re-resolution of a caller changes `row_key`, so the new key is counted again and the old key's shrink is ignored (negative deltas are never subtracted); history now reaches 35 days (raw traces 1 day); agent traces are included; auth anomalies are evaluated per 5-minute row; the telemetry gate counts requests not spans; a legacy checkpoint upgrade can skip at most one cycle; known IPs for Detector 9 exclude anonymous principals' IPs. The ELK path (`elk_to_clickhouse`) is unchanged and also feeds the rollup through the ClickHouse `traces` copy.
- **Reset:** `rebuild_clickhouse_analytics.py` truncates the ledger but deliberately keeps `principal_activity_5m` (its history cannot be rebuilt from 1-day raw traces); the checkpoint reset triggers a bootstrap that replays the kept rollup.
- **Mid-request outgoing calls (`client_exit`):** `trace_edges.resolve(..., exit_clients=True)` (used by `trace_edge_resolution` for OTLP rows stored one-per-span) turns a non-root client span that is contained in a server span and names a different peer into a `caller -> peer` dependency edge, confidence 0.7, instead of dropping it. The client span's own row is counted at the edge (`client_exit`), the enclosing server row is untouched. Root clients still use `client_retargeted`. Tests: `tests/test_otlp_trace_edge_resolution.py` (mid-request section).
- **Scripts:** `generate_{7,10,30}day_*`, `generate_2m_enterprise_dataset.py` and `send_traces.py` call `materialize_principal_activity` before behavior/anomaly processing.
- **Tests (run serially):** principal suites 18/18, boundary + user/IP + identity + worker-start + OTLP resolution + behavior-access suites pass. Full suite (serial, `--ignore=tests/test_learned_behavior.py`): 360 passed, 1 skipped, 7 failed; none caused by this work: 5 also fail at a clean HEAD worktree (`test_analytics` worker-checkpoint + byte-bucket tests, `test_elasticsearch_storage` worker sync, `test_interactive_service_topology` operation name, `test_behavior_topology` expected_tps), 2 pass when the host `.env` is absent (`test_agent_traces_only` ES-sync skip, `test_trace_edges` metric-window; the `.env` sets `OTEL_ES_SYNC_ENABLED` / `OTEL_TRACE_EDGE_SKEW_MS`).
- **Deployed (2026-10-01):** `xhatsu101/tracescope:0.4.6`, `app-0.4.6`, `ingest-0.4.6` pushed; `helm upgrade tracescope` rev 4 (chart 0.3.10, app 0.4.6) (rev 4 used a minReplicas=3 override); rev 5 (same chart/images) dropped the override per user request: ingest HPA min 1 / max 12 (chart defaults), HPA drives scale; note HPA shows cpu unknown without metrics-server, so it will stay at 1 until metrics exist. ClickHouse was not restarted by the upgrade plan. Verified with helm/curl only (kubectl is forbidden).
- **Deploy verification (2026-10-01, rev 5):** the upgrade hit the known deadlock again (ClickHouse Pending `Insufficient cpu`, PV pinned to one node, ingest surge holding the CPU, migrate init CrashLoopBackOff). With the user's explicit permission for that step only, recovery was `kubectl scale deploy/tracescope-ingest --replicas=0`, wait for ClickHouse/app Ready, then `--replicas=1` (HPA min 1 / max 12; cpu shows `<unknown>` without metrics-server so it stays at 1). After recovery: app 2/2, migration 019 applied (`"status": "migrated"`), `principal_activity_5m` 24 rows / 9 principals, `principal_activity_consumed` 24, worker cycles succeed, public `/api/v1/*` pages return 200, `/api/v1/users` lists principals. Prevention: scale ingest to 0 BEFORE a chart upgrade that reschedules ClickHouse, or give ClickHouse a PriorityClass/requests that fit.
- **Host:** `.env` has `OTEL_CLICKHOUSE_HOST=10.108.134.22` and `OTEL_HOST_WORKER_ENABLED=false`. Local FastAPI dashboard started on `:30102` (`tracescope-30102` tmux session) and bootstrap on `:30105`. Host worker is explicitly disabled (no `tracescope-worker` session; cluster worker owns analytics).
- **Not done:** no commit.

## tracescope-obi Helm chart (renamed from otel-obi 2026-10-01; chart renamed in the repo only, live release still `otel-obi`)

- **Rename:** chart `deploy/helm/tracescope-obi/` (release default `tracescope-obi`, `render-stack.sh --obi-release`, default `<ts-release>-obi`), installed in the SAME namespace as the app (`tracescope`; `--obi-namespace` default changed from `observability`). Resources: Deployment/Service `tracescope-obi-collector` (DNS `tracescope-obi-collector.tracescope.svc.cluster.local:4317`), DaemonSet/ServiceAccount/ClusterRole(Binding) `tracescope-obi`, labels `app.kubernetes.io/part-of=tracescope`. Fullname rule mirrors the app chart: release names containing `tracescope` are used as-is, else `<release>-tracescope-obi`. Generated files are `tracescope-obi-values.yaml` / `tracescope-obi.yaml`.
- **Live cluster MIGRATED (2026-10-01, kubectl authorized by user):** Uninstalled the old `otel-obi` Helm release from namespace `observability`. Used `render-stack.sh --mode clickhouse --obi custom --body on --target default --exclude kube-system --out ./stack-out --render` to build declarative YAMLs. Applied `tracescope.yaml` and `tracescope-obi.yaml` to namespace `tracescope`. Resources now match the app: `tracescope-obi` DaemonSet and `tracescope-obi-collector` Deployment/Service. Verified OBI eBPF captures XML/SOAP bodies (e.g. `emma_wsse`), collector exports to `tracescope-ingest:30103` (200 OK), traces write to ClickHouse, and background worker cycles pass cleanly.

- New chart `deploy/helm/otel-obi/` (0.2.0), separate from `tracescope` because OBI is privileged/cluster-scoped. Supersedes `~/agy/otel-obi/chart` (0.1.0).
- `obi.variant`: `standard` (upstream `otel/ebpf-instrument:v0.13.0`, headers + JSON bodies) or `custom` (`xhatsu101/ebpf-instrument:xmlCustom-0.13.0`, XML bodies for SOAP/WSSE; arm64 only). `obi.bodyCapture.enabled` plus per-scope request/response switches. Targets are set through `obi.discovery.instrument`/`excludeInstrument`/`extra`; `obi.extraConfig` deep-merges raw OBI config.
- `collector.exporter.mode`: `elk` (OTLP to APM Server) or `tracescope` (otlphttp to TraceScope `/v1/traces`; no custom ingestion needed; TraceScope must use `pipelineMode=clickhouse`, ES sync off, `clickhouseOnlyAgentTraces=false`). Optional X-API-Key from a Secret.
- Collector deletes `http.request.header.authorization` and `x-wsse` after WSSE extraction by default (`collector.redaction.*`); `dropBodies` optional. Collector pinned to 0.161.0.
- `deploy/helm/render-stack.sh --mode elk|clickhouse` (POSIX sh) generates matching `tracescope-values.yaml` + `otel-obi-values.yaml` (and manifests with `--render`). clickhouse mode: TraceScope `ingest.enabled=true`, `pipelineMode=clickhouse`, ES off; collector `otlp_http` -> `<release>-ingest:30103`, batch 2000/max 5000 (TraceScope 413s above 10000 spans/10 MiB), bodies dropped.
- Collector -> TraceScope ingest transport verified with a real collector 0.161.0 and the TraceScope parser (gzip protobuf, WSSE principal, redaction).
- **Cluster test deploy (2026-10-01, kubectl authorized for this task):** uninstalled both old releases (tracescope rev 2 incl. ClickHouse PVC/PV, reclaim=Delete; otel-obi 0.1.0), then installed `tracescope` (rev 1, `--mode clickhouse`: 3 ingest pods, NodePort 30103, ES off) and `otel-obi` 0.2.0 (custom OBI, body on, target `default`, collector -> `tracescope-ingest:30103`). New ClickHouse ClusterIP `10.108.134.22` (host `.env` still has the old `10.98.4.14`; host dashboard/worker need updating). Old non-Helm `tracescope-apm-server`/`tracescope-elasticsearch` Services left untouched. HPA shows `cpu: <unknown>` (no metrics-server), so ingest stays at 3 replicas.
- Live result in clickhouse mode with image 0.4.3 (before the fix below): spans flow and WSSE principals are attributed, but there was no server-span caller, OBI client spans became `unknown-downstream` and fake edges, bytes were 0 and operations duplicated as `/path` vs `METHOD /path`.
- Verified: helm lint, renders in all modes, `otelcol-contrib validate` passes for both exporter modes, and both OBI images log `configuration loaded` for the rendered config.

## Relationship Observed IP Evidence & Access Flow IP Integration (2026-10-01)

- **Root Cause of Missing IP Data Across Relationships**:
  1. **Behavior Learning Disconnect from IP Datastore**: When the behavior learning pipeline transitioned from raw Elasticsearch trace documents to ClickHouse metric buckets, `sql_day()` in `backend/app/services/behavior_sources.py` queried only table `metric_buckets`. Because `metric_buckets` is an aggregated transaction table that does not contain source IP columns, `row.get('observed_ips')` was always empty (`[]`).
  2. **Empty Learned Graph IP Nodes & Edges**: Because `row.get('ips')` was always empty, the online behavior graph engine (`backend/app/services/behavior_graph.py`) generated zero `ip` nodes and zero `peer_on_call` edges. Consequently:
     - `/api/v1/behavior/topology` returned `ip_associations: []`.
     - `/api/v1/behavior/access` returned `ip: { roles: [], total: 0 }`.
     - Interactive Topology inspector showed `Observed IP evidence (0) -> No observed IP evidence.`
  3. **Frontend Edge Selection Excluded IPs**: In `frontend/src/pages/InteractiveTopology.tsx`:
     - Line 730 filtered `selectedRelations` using `selectedNode`. When an edge was selected (`selection.kind === 'edge'`), `selectedNode` was `undefined`, resulting in zero matched relations.
     - Line 600 only rendered the IP evidence drawer for `selection.kind === 'node' && selection.node.type === 'principal'`, completely hiding IP evidence when inspecting relationship edges or APIs.
- **Fix Applied**:
  - In `backend/app/services/behavior_sources.py`:
    - Updated `sql_day()` to perform an equi-join with `topology_principal_ip_5m FINAL`, pulling `arrayDistinct(groupArray(tuple(t.source_ip, t.source_ip_role))) AS observed_ip_tuples` grouped by transaction context.
    - Updated `normalize()` to parse `observed_ip_tuples`, assigning infrastructure vs client/unverified_peer roles.
  - In `backend/app/services/behavior_worker.py`:
    - Refreshed the behavior learning pipeline to learn against the joined IP dataset.
    - Generated 47+ `peer_on_call` edges and 10+ `ip` nodes in the online behavior graph.
  - In `frontend/src/pages/InteractiveTopology.tsx`:
    - Updated `selectedRelations` to match `relation.edge_id === selection.edge.id` when selecting an edge.
    - Deduplicated `ipItems` by `source_ip` to present clean distinct IP addresses.
    - Updated `DetailPanel` to render the `Observed IP evidence ({ips.length})` drawer for service call edges, APIs, and principals.
  - Rebuilt production frontend via `npm run build` and restarted dashboard stack via `./run_server.sh restart`.
  - Verified live:
    - `/api/v1/behavior/topology` returns 47 active `ip_associations`.
    - `/api/v1/behavior/access?focus_type=service&focus=order-service` returns 4 client IP roles and full IP connectivity.
    - All verified endpoints return HTTP 200.

## Topology Straight Slim Line Styling (2026-10-01)

- **Change Summary**:
  - In `frontend/src/pages/InteractiveTopology.tsx`:
    - Removed `strokeDasharray={style.dash}` on SVG graph edge paths so all relationship lines render as solid, straight, unbroken lines without dashes.
    - Set `edgeStrokeWidth` and `strokeWidth` to a clean, slim stroke of 1.2px (and 2.0px when selected), replacing heavy TPS-scaled thicknesses (previously up to 9px).
    - Preserved invisible 16px hover/hit area so slim lines remain easily clickable.
    - Simplified bottom status legend to remove the obsolete "Width = TPS" note.
  - In `frontend/src/pages/Topology.tsx`:
    - Updated canvas edge rendering to a fixed slim `x.lineWidth = 1.2` and cleared `x.setLineDash([])` (previously `[6, 5]` on inferred edges).
    - Updated description to remove reference to dashed calls.
  - Rebuilt production frontend via `npm run build` and verified live assets served by FastAPI.
  - Verified live: `/api/v1/health`, `/api/v1/behavior/topology`, and `/api/v1/topology` return HTTP 200 with active nodes and edges.

## Dashboard TPS Settling Window & ClickHouse FINAL Deduplication Fix (2026-10-01)

- **Root Causes of Inaccurate Current TPS**:
  1. **Partial In-Progress Window**: The dashboard series query returned the open minute/5m bucket whose full duration had not yet elapsed (e.g., only 15-20s of requests collected). Because the query divided the partial request count by the fixed window duration (60s or 300s), the calculated TPS appeared heavily deflated (e.g., 1.85 TPS vs 7.5 TPS). Once the window closed and all traffic arrived, the number jumped back to normal ("right after that window").
  2. **Worker Batch Sync Lag**: The background worker runs every 60s. During an open minute, traces continue accumulating in Elasticsearch and are only synced to ClickHouse in the subsequent cycle, making the in-progress bucket incomplete in ClickHouse until the window ends and the worker runs.
  3. **Missing `FINAL` on `ReplacingMergeTree`**: In `backend/repository.py`, queries against `metric_buckets` lacked the `FINAL` keyword. When the worker re-aggregated active slices, unmerged parts on disk resulted in duplicate counts (e.g., 914 requests vs 457 true requests, inflating TPS to 15.23).
- **Fix Applied**:
  - In `backend/repository.py`:
    - Added `FINAL` to all `metric_buckets` queries across `dashboard_summary`, `dashboard_series` (both 60s and multi-minute aggregation branches), and `rankings` (all 5 category rankings).
    - In `dashboard_series`, bounded live time ranges to settled completed windows (`bucket_start <= effective_end_sec - grain_sec`, with 60s worker settling grace). Open, incomplete buckets are excluded from time series so rate calculations are never artificially deflated.
  - In `backend/app/repositories/aggregate_repository.py`:
    - Added `FINAL` to `metric_buckets` and bounded `query_series()` to settled windows (`effective_end_sec = min(end_sec, now_sec - 60)`, `bucket_start <= effective_end_sec - bucket_size`), automatically propagating settled deduplicated data to Service detail metrics, API detail metrics, and Principal series.
  - In `backend/app/api/services.py`, `backend/app/api/overview.py`, `backend/app/api/principals.py`, `backend/app/api/anomalies.py`:
    - Added `FINAL` to all `FROM metric_buckets` queries (`list_services`, `get_service_detail`, `top_services`, `top_principals`, `slowest_operations`, `get_principal_relationships`, `format_anomaly`).
  - In `frontend/src/pages/Overview.tsx`, `frontend/src/pages/Services.tsx`, `frontend/src/pages/ApiDetail.tsx`:
    - Filtered time series for completed buckets (`timestamp_ms + bucketMs <= Date.now()`), guaranteeing KPI throughput cards ("Current throughput", "Current TPS") always display settled, accurate TPS without in-progress deflations.
  - In `frontend/src/components/ChangeVisualEvidence.tsx`:
    - Filtered series points to completed buckets (`point.timestamp_ms + 60_000 <= nowMs`) so baseline and post-change observed TPS means (`mean(afterPoints)`) are not dragged down by partial buckets.
    - Bounded X-Axis domain to `[start, Math.max(pivot + 60_000, Math.min(end, nowMs))]`, eliminating the 55-minute future blank space when viewing recent change episodes.
  - In `frontend/src/components.tsx`:
    - Updated `TpsLineChart` to pick `completedData` for its latest TPS badge, ensuring shared reusable charts never display un-settled rates.
  - Rebuilt production frontend via `npm run build` and restarted dashboard and worker stack via `./run_server.sh restart`.
  - Verified live:
    - `/api/v1/dashboard/series` returns consistent 7.13 - 7.67 TPS with 0 cliff drops and 0 duplicates.
    - `/api/v1/services/order-service/metrics` returns consistent 2.4 - 2.5 TPS with 0 cliff drops.
    - `/api/v1/principals/bob_wsse/metrics` returns consistent 0.45 TPS with 0 cliff drops.
    - `/api/v1/topology/apis/POST%20%2Fapi%2Fv1%2Forders%2Fprocess/metrics?service=order-service&window=1h` returns consistent 2.48 - 2.53 TPS.
    - All verified endpoints return HTTP 200.

## Database Wipe & Clean Server Restart (2026-09-30 17:27 UTC)

- Executed `backend/scripts/reset_testbed.py`: cleanly truncated 61 ClickHouse analytical tables in database `tracescope` and deleted Elasticsearch indices (`apm-*`, `traces-apm*`, `tracescope-*`) with HTTP 200. ClickHouse system telemetry logs truncated.
- Updated `backend/config.py` to auto-load `.env` via `python-dotenv` and added `10.98.4.14` to candidate socket fallback IPs, guaranteeing CLI scripts inherit connection settings without manual shell exports.
- Restarted TraceScope dashboard server and background worker via `./run_server.sh restart`.
- Verified live state:
  - tmux sessions active: `tracescope-30102` (FastAPI) and `tracescope-worker`.
  - Ports listening: `0.0.0.0:30102` and `0.0.0.0:30105`.
  - All verified endpoints return HTTP 200: `/health`, `/overview`, `/services`, `/principals`, `/users`, `/traces`, `/topology`, `/anomalies`, `/ingestion/status`, `/dashboard/series`.
  - Background worker completed full cycle with 0 errors.

## Production Image 0.4.3 Build & Helm Release 2 Upgrade (2026-09-30)

- Built and pushed production multi-stage images: `xhatsu101/tracescope:0.4.3`, `xhatsu101/tracescope:app-0.4.3`, `xhatsu101/tracescope:ingest-0.4.3`.
- Updated Helm chart `deploy/helm/tracescope/Chart.yaml` to `version: 0.3.7`, `appVersion: 0.4.3` and `values.yaml` to `global.image.tag: 0.4.3`.
- Upgraded Helm release `tracescope` in namespace `tracescope` (Revision 2).
- Verified live state: `tracescope-app-0` (2/2) and `tracescope-clickhouse-0` (1/1) Running with 0 restarts.
- Endpoints verified healthy (HTTP 200 on both cluster ingress `https://trace.n2d.id.vn` and local host `:30102`): `/health`, `/overview`, `/services`, `/principals`, `/users`, `/traces`, `/topology`, `/anomalies`, `/dashboard/series`, `/ingestion/status`.

## OBI root-client direction fix (activated in 0.4.3)

- Normalization infers a client for parentless transactions without explicit span kind only when an outbound peer matches the URL host or server address. Caller-only fields cannot trigger the inference; explicit server kinds remain server. Inference uses `root_client_inferred`, confidence 0.8.
- Six isolated regression tests passed (`tests/test_obi_root_client_normalization.py`, `--noconftest`). Activated in production image `0.4.3` and Helm release 2.

## Canonical two-mode ClickHouse pipeline (2026-09-30)

- The only supported analytical shape is normalized ClickHouse `traces` followed by the ClickHouse worker aggregation/read model.
- `OTEL_TRACE_PIPELINE_MODE=elk_to_clickhouse` (default) copies ELK raw traces into ClickHouse; `OTEL_TRACE_PIPELINE_MODE=clickhouse` uses existing ClickHouse traces and does not contact ELK for synchronization.
- Direct Elasticsearch metric/IP materialization is disabled in the normal worker. ELK must not write `metric_buckets` or topology tables directly.
- Analytics, topology, and trace explorer read ClickHouse in both modes. Use `backend/scripts/rebuild_clickhouse_analytics.py` to reset derived tables while preserving raw traces and rebuild them through the worker.
- Verified live after rebuild: worker success, 34,626 traces, 3,751 1m buckets, 777 5m buckets, and health reports the selected pipeline mode plus ClickHouse metric/topology sources.

## ClickHouse Trace Aggregator & Dual-Aggregator Unification (2026-09-30)

- **Root Cause of Split Operations**: SOAP-over-HTTP requests carried both a REST URL path (`POST /api/v1/orders/process`) and an XML SOAPAction header (`"processOrder"`). While Elasticsearch aggregated under the canonical HTTP route, the ClickHouse trace aggregator (`backend/app/services/aggregation.py`) prioritized `operation_key` (`orderservice/"processOrder"`). Because the operation strings differed, ClickHouse `ReplacingMergeTree` did not deduplicate them, causing traffic to split into 3-4 separate operations on the service board.
- **Why System Uses Both Aggregators**:
  1. `_run_elasticsearch_metrics()`: Fast historical slice and IP topology materialization directly from Elasticsearch APM documents into `metric_buckets`.
  2. `aggregate_traces()`: Aggregates ClickHouse `traces` table (populated by HTTP ingest and background trace sync for principal intelligence).
  3. Both write into ClickHouse table `metric_buckets`, which uses `ENGINE = ReplacingMergeTree` ordered by `(bucket_size, bucket_start, caller_service, target_service, principal_name, operation)`. When both aggregators emit the identical canonical route key, ClickHouse automatically deduplicates and replaces them into single clean records.
- **Unification Implemented**:
  - In `backend/app/services/aggregation.py`, updated line 31 `_BUCKET_AGGREGATION_SQL` to prioritize `operation` (`POST /api/v1/orders/process`) over `operation_key`, aligning with `_SHADOW_AGGREGATION_SQL`.
  - In `backend/app/services/normalization.py`, updated `normalize_operation_key()` to preserve canonical HTTP routes (`METHOD /path/{id}`) when present rather than overwriting them with XML SOAPAction headers, and stripped literal quotes from RPC methods.
  - Cleared legacy mangled operation keys across ClickHouse `traces` and `metric_buckets`.
- **Verification**: `GET /api/v1/services/order-service` now serves only 2 unified canonical operations: `POST /api/v1/orders/process` and `POST /api/v1/payments/process`. All services across the estate are 100% unified with zero duplicate operations.

## Behavior Learning Backfill Acceleration & Post-Wipe Recovery (2026-09-30)

- **Root Cause of Empty Learned Behavior**: After the database wipe, `backend/app/services/behavior_worker.py` defaulted `state['next_day']` to 30 days in the past (Sep 1). Because line 84 guarded `min(bucket_start)` lookups with `if not state.get('next_day')`, it never re-evaluated the actual available data timestamp, slowly stepping forward 1 empty day per 60-second cycle (~30 minutes of empty backfill).
- **Accelerated Earliest Bound**: Removed `and not state.get('next_day')` so `earliest` is always bounded by `min(bucket_start) // DAY * DAY`. When data starts today or after a reset, empty past days are skipped instantly in 0 ms.
- **Immediate Live Graph**: Behavior engine advanced to live mode: `/api/v1/behavior/overview` now serves 63 active profiles, 34 nodes, 104 edges, and 85 learned relationships.
- **Familiarity State Clarification**: New profiles display as `emerging` ("Đang học" in Vietnamese) rather than `established` because TraceScope platform invariants require &ge; 3 clean observation days, &ge; 5 count samples, and &ge; 7 days of elapsed history before elevating an emerging relationship to `established`.

## Standardized Production .env Configuration & Settings Unification (2026-09-30)

- **Comprehensive Configuration**: Standardized `.env` and `.env.example` into 11 clearly documented, cohesive sections: Core Server, Storage Architecture, ClickHouse Datastore, Elasticsearch Datastore, Ingestion Pipeline, Network Topology/Proxies, Behavioral Analytics, Principal & User Intelligence, AI Semantic Assessment (L4), Alerting, and LLM Deep Investigations.
- **Settings Property**: Added `elasticsearch_sync_enabled` to `backend/config.py` (`Settings` dataclass) and updated `backend/worker.py` to reference `settings.elasticsearch_sync_enabled`, eliminating ad-hoc `os.environ.get()` calls and missing import errors.
- **Server Startup Integration**: Updated `run_server.sh` to source `.env` automatically upon startup, ensuring all overrides (`OTEL_PORT`, `OTEL_ES_PORT`, `OTEL_STORAGE_BACKEND`, etc.) apply across both the dashboard server and background worker tmux sessions.
- **Verification**: Restarted services via `./run_server.sh restart` and verified HTTP 200 on `/health`, `/overview`, `/services`, `/principals`, `/users`, `/traces`, `/dashboard/series`, and `/ingestion/status`. Worker stage `process_elasticsearch` runs with zero errors.

## Faster behavior learning watermark (2026-09-30; worker not restarted)

- `behavior_worker.learnable_end()` learns a five-minute window `OTEL_BEHAVIOR_LEARN_GRACE_SECONDS` (default 90, clamp 30-300) after it closes once its one-minute `metric_buckets` exist; otherwise falls back to the former `(now//BUCKET-1)*BUCKET` lag. Learned-through never regresses (a dropped window would force full replay). Late data changing a learned window triggers the existing full graph replay (~3.6 s).
- Live read-only check: learned-through lag 9.5 min -> 4.5 min at the same instant; expected steady range ~1.5-6.5 min plus worker cycle.
- Topology `ObservationAge` now counts from window end (`last_seen_ms` + 5 min, capped at now); API fields unchanged. Frontend rebuilt/served.
- Topology spider layout (`frontend/src/topologyLayout.ts`) is now group-first: components/label-propagation communities laid out separately, circle-packed next to linked groups (canvas-aspect aware), rotated toward partners, unlinked services grouped last. Synthetic check: same-group vs cross-group distance ratio ~1.0 -> 2.5-12x, 0 overlaps, deterministic, 500 services 238 ms.
- Tests: `tests/test_behavior_learn_window.py` 4/4; behavior graph/topology 26/27 (the 1 failure is the pre-existing `topology_series` `expected_tps` one).
- Activation pending: `./run_server.sh restart` (also activates trace-resolved edges, policy v2, v4 learning).

## Trace-resolved service edges (2026-09-30; worker not restarted)

- `backend/app/services/trace_edges.py` resolves each server transaction's caller from trace data: `parent.id` join (SDK agents), else same-`trace.id` peer-name + time-containment match with clock-skew tolerance (OBI eBPF: live parent IDs are 0/2,000 resolvable), else explicit caller fields, else socket-peer IP (`OTEL_SERVICE_IP_MAP` operator map, then IPs learned from resolved edges; LB/proxy/NAT never attributed), else `time_correlated` pairing of a root request with a leftover client call from another trace (caller propagated no context), else no caller. An exit span to a different peer than the callee makes that uninstrumented hop the caller (`trace_intermediary`).
- Root "transactions" that are really client calls (e.g. `traffic-ui`, `legacy-service`) are skipped when paired, else retargeted to the observed peer (external hosts keep their full hostname).
- `ElasticsearchMetricRepository` processes windows in 15-minute bucket-aligned slices (resumable `{"slice_start_ms", "after"}` cursor), fetches minimal trace fields per slice (+/-60 s context, halving above 10k docs), and overrides `topology.caller`/`topology.target`/`topology.metric_operation` runtime fields through script params; paired client roots are excluded via `topology.trace_skip`. Applies to `metric_buckets` and `topology_principal_ip_5m`. Slices ending in the last 2 h are cleared (ClickHouse lightweight DELETE) before rewrite so superseded caller keys do not linger. Tunable skew: `OTEL_TRACE_EDGE_SKEW_MS` (default 250).
- Worker `bytes_schema_version` 2 -> 3 triggers one rebuild limited to the range Elasticsearch still retains; older buckets are kept.
- `normalization.py` no longer labels unverified peer attributes as `trace_parent` (now `header`, 0.8).
- Read-only live check (15 min): traffic-ui -> order-service 2,699, legacy-service -> order-service 112, order-service -> payment-service 2,810, payment-service -> notification-service 2,811; external dependencies cloudflared-music -> ingress-nginx-controller.ingress-nginx and osclient-web -> *.supabase.co. Tests: `tests/test_trace_edges.py` + rollup tests 21/21; related suites 50/50. Pre-existing failures (also without this change, `--noconftest`): 3 in `test_identity_normalization_and_incidents.py`, 2 in `test_worker_start_time.py`.
- Activation pending: `./run_server.sh restart` also activates the other pending policy-v2 and v4 learning changes and may raise new-service-edge changes/alerts for the newly visible edges.

## Changes impact policy v2 (implemented, backend activation pending)

- `change_policy.py` now evaluates informational / Watch / Needs attention / Critical using structured impact and distinct observation buckets, not relative delta or detector count alone. `expected` remains a compatibility state with separate evaluated impact/disposition.
- Service detectors emit baseline/count/bucket evidence; coalescing retains three distinct windows. Auth evidence uses scoped failure/success counts. UI supports Watch; API preserves `previous_evaluation` for comparison.
- 22 isolated policy/L4/API tests and frontend build passed. Read-only replay: all 31 prior critical episodes become Watch because legacy structured evidence is insufficient; review before activation. Backend and worker were NOT restarted. Frontend bundle rebuilt.
- See `docs/change-policy-v2.md` for thresholds, rollout caveats and deferred persistent lifecycle/notification work.

## Trace Metadata Synchronization to ClickHouse (Safety & Architectural Invariants)

- **Purpose & Scope**: Writing trace transaction headers into ClickHouse `traces` is safe, optimal, and essential for the platform's analytical intelligence (`process_principal_intelligence`, caller-target relationship graphs, user behavior profiles, and incident blast-radius traversal).
- **Strict 1-Day TTL**: ClickHouse `traces` table enforces a strict 1-day TTL (`TTL toDateTime(intDiv(timestamp_ms, 1000)) + toIntervalDay(1)` via Migration 009). ClickHouse automatically merges and truncates expired partitions in the background, strictly bounding disk usage (~4.5 GB at 12 TPS).
- **Separation of Concerns with Elasticsearch**: Elasticsearch retains full multi-tier span trees for 2 days (via ILM policy `tracescope-2day-retention` and worker background `_delete_by_query`). Detailed span waterfalls on `/traces/:id` are served directly by Elasticsearch (`OTEL_TRACE_STORAGE_BACKEND=elasticsearch`), while ClickHouse handles high-speed analytical queries.
- **In-Memory Credential Sanitization**: Passwords, tokens, and WSSE secrets are scrubbed in-memory before trace records are inserted into ClickHouse.
- **Enabled Status**: `OTEL_ES_SYNC_ENABLED=true` ensures the worker keeps user behavior, principal intelligence, and access matrices updated continuously.
- **Worker User Sync Gate Fix (2026-09-30)**: `_run_elasticsearch_sync()` in `backend/worker.py` previously skipped `reader.sync()` when `clickhouse_only_agent_traces` was True. Fixed to respect `OTEL_ES_SYNC_ENABLED=true`. Initial sync inserted 7,732 traces and processed 4,150 transactions. `/api/v1/users` now successfully serves all 9 active users (`bob_wsse`, `alice_wsse`, etc.) with established baselines.

## Canonical Route Standardization (Option 1 Implemented, 2026-09-30)

- **Standardization on Canonical Route (`METHOD /path/{id}`)**: Both `ElasticsearchMetricRepository` (`topology.metric_operation` Painless script) and `InteractiveTopologyRepository` (`topology.api` runtime field) now emit the exact canonical HTTP transaction format (e.g., `POST /api/v1/orders/process`) with dynamic numeric and UUID path parameters masked to `/{id}`. The intermediate route path is no longer collapsed to `{first}/{last}`.
- **Unified Service Access Board**: Because both `metric_buckets` and `topology_principal_ip_5m` now produce identical operation keys, [`ServiceAccessBoard.tsx`](file:///home/ubuntu/Viettel/OtelTrace/frontend/src/components/ServiceAccessBoard.tsx) deduplicates them seamlessly into single clean rows without visual duplication or double-counting.
- **Helm Release Deployment**: Re-deployed Helm release `tracescope` in namespace `tracescope` (`deploy/helm/tracescope/` with values and secrets, `app.image.tag=app-0.4.0`). ClickHouse StatefulSet is healthy and reachable at ClusterIP `10.98.6.4:8123`.
- **Database Wipe & Reset**: Executed `backend/scripts/reset_testbed.py`: cleanly truncated all 61 ClickHouse analytical tables and deleted Elasticsearch APM indices (`apm-*`, `traces-apm*`, `tracescope-*`). Truncated ClickHouse system logs.
- **Host Stack Restart**: Restarted dashboard and worker via `./run_server.sh restart`. Verified healthy endpoints (HTTP 200) for `/health`, `/overview`, `/services`, `/principals`, `/traces`, `/ingestion/status`. Worker runs cycles cleanly with zero ClickHouse connection errors.

## Database Reset & State Wipe (2026-09-30 05:32 UTC)

- All 61 ClickHouse analytical tables in database `tracescope` truncated cleanly (preserving `schema_migrations` and `principal_readiness_summary_mv`).
- Elasticsearch APM and TraceScope indices (`apm-*`, `traces-apm*`, `tracescope-*`) deleted (HTTP 200).
- ClickHouse system telemetry logs truncated to minimize disk usage.
- Worker and dashboard restarted fresh via `run_server.sh restart`.
- Verified live endpoints returning HTTP 200: `/health`, `/overview`, `/services`, `/principals`, `/topology`, `/anomalies`, `/traces`, `/ingestion/status`.
- **60s Metric Buckets & Dual-Worker Conflict Resolution**: A deployed Kubernetes cluster pod (`10.244.1.198`) running revision 27 of the Helm release runs with `bytes_schema_version = 2`. When uncommitted local code updated `bytes_schema_version` to 3, the two workers entered an alternating conflict loop where each saw the other's checkpoint version as obsolete and called `delete_window()`, constantly wiping older 60s buckets and leaving only the 10-minute sliding window. Re-aligning `bytes_schema_version = 2` across local code and tests resolved the conflict completely: `/api/v1/dashboard/series` now stably accumulates 91+ consecutive 1-minute data points (from 12:31 UTC+7 onward) without unwanted truncations.

## Elasticsearch Worker Materialization of 5-Minute IP Topology (2026-09-30)

- `ElasticsearchMetricRepository` implements `materialize_ip_window` which aggregates Elasticsearch transactions into 5-minute IP relationship records (source IP, target service, API operation, caller service, principal, request counts, errors, 4xx/5xx/auth failures, bytes, p95 latency).
- Client source IPs are classified using `classify_source_ip_role` and durably inserted into ClickHouse tables `topology_principal_ip_5m` and `topology_principal_ip_current`.
- `backend/worker.py` (`_run_elasticsearch_metrics`) continuously materializes `live_start` to `live_end` IP windows on every cycle alongside `metric_buckets`, and automatically bootstraps the 2-day historical trace retention in 24-hour slices.
- Service Access Boards, User IP profiles, and topology IP endpoints query ClickHouse directly with sub-millisecond latency without on-demand Elasticsearch script aggregations.

## Learning engine level-shift adaptation and replay benchmark (2026-09-30; not activated)

- Online graph `online-behavior-graph-v4`: after 27 of the last 36 eligible windows are material surges, the TPS reference re-seeds to the new level (median/MAD) and records `level_shift`. The profile same-hour TPS reference restarts at that point. Previously a permanent increase alerted indefinitely. Shorter surges and incident/gap windows are still withheld.
- Added a labelled offline benchmark, `backend/scripts/benchmark_behavior.py` (no DB). It is 6/7 on seeds 1/2/3/7. Level-shift stale alerts dropped from 61 to 0. Known gap: a 2.5x surge on a high-volume API is missed because of the fixed 3x floor. The worker's graph-deviation logic is extracted as the pure `graph_deviations()`.
- Tests: `tests/test_behavior_graph.py` 17/17, including 5 new tests and a benchmark smoke test. Pre-existing on HEAD: `tests/test_learned_behavior.py` fails to import `es_query`, and 5 of its tests exercise the removed ES source. `test_behavior_topology.py::test_service_edge_reinforces_once_with_multiple_apis` fails due to the uncommitted `topology_series` `expected_tps` change.
- Read-only live dry run: v4 full replay took 3.6 s; 0 live level shifts; deviations unchanged (30 `access_expansion`). Worker NOT restarted. Activation (`./run_server.sh restart`) triggers one automatic full replay.

## 1. Project Overview
**TraceScope** is an OpenTelemetry transaction analytics and behavioral observability platform for large service estates.
- **Core Functionality**:
  - Ingests Elasticsearch APM JSON/NDJSON, canonical OTLP JSON subsets, and NetworkTracing old-kernel capture envelopes/events with tolerant optional-field handling.
  - Sanitizes Basic authentication in-memory (passwords and tokens scrubbed before storage/logging/hashing).
  - Analytical data model: `caller_service` -> `principal_name` -> `target_service` -> `operation` -> `status + latency`.
  - Computes 1-minute (`60s`) and 5-minute (`300s`) rollups with exact p50/p95/p99 percentiles.
  - Computes rolling medians and MAD (Median Absolute Deviation) baselines across matching minute-of-week and hour-of-day. Worker baseline training stops before the earliest pending five-minute anomaly window and excludes windows covered by detected service metric incidents, so later spikes cannot train their own reference.
  - Detectors: Traffic spike (`traffic_spike`), traffic drop (`traffic_drop`), latency shift (`latency`), error rate increase (`error_rate`), new service relationship (`new_service_edge`), new principal relationship (`new_principal_edge`), unusual access (`unusual_access` / "Truy cập Bất thường"), unusual execution time (`unusual_time`), and source IP behavioral anomalies (`user_new_source_ip` / `ip_new_user`).
  - Incident blast-radius analysis (upstream callers, affected principals/operations) and deterministic root-cause heuristic origin.
  - Serves fast analytics dashboards via FastAPI and an interactive React/TypeScript frontend.
- **Storage Invariant**: OTel trace data from application services is stored in Elasticsearch (`tmp-elk-svc`) with a strict **2-day maximum retention** policy enforced via ILM policy (`tracescope-2day-retention` and override of `apm-rollover-30-days` with delete phase after 2 days) and worker background asynchronous pruning (`_delete_by_query` on `@timestamp < now - 2d`). ClickHouse trace data copied for worker SQL calculations enforces a strict **1-day TTL** (`TTL toDateTime(intDiv(timestamp_ms, 1000)) + toIntervalDay(1)` via Migration 009). This ensures both ClickHouse and Elasticsearch disk usage stays strictly bounded and minimal (stabilizing at ~4.5 GB at 12 TPS), while Elasticsearch serves multi-tier span waterfalls on `/traces/:id` up to 2 days.
- **Root Directory**: `/home/ubuntu/Viettel/OtelTrace`
- **Active Storage**: Application APM traces are read from Elasticsearch (`http://127.0.0.1:32073`); ClickHouse (currently reached at `10.105.101.253:8123`) holds worker metric buckets and other derived data. `run_server.sh` defaults analytics to `OTEL_STORAGE_BACKEND=clickhouse` and Trace Explorer to `OTEL_TRACE_STORAGE_BACKEND=elasticsearch`. Set the latter to `clickhouse` explicitly for an offline ClickHouse trace testbed. `OTEL_ES_URL` alone configures the ELK connection but does not select the trace read backend.
- **Helm ELK Wiring**: The chart keeps analytics on ClickHouse, uses `storage.traceBackend=elasticsearch` for raw trace reads, and defaults worker ELK requests to `http://tmp-elk-svc.tmp-elk.svc.cluster.local:9200`. `elasticsearch.enabled=false` clears the URL passed to the worker. Helm release `tracescope` is now revision 27 with this configuration; the app/worker pod is healthy and the worker is materializing ELK metrics into ClickHouse.
- **Active Dashboard Port**: `0.0.0.0:30102` (lifecycle-script default and current listener).
- **NetworkTracing Hub Port**: `0.0.0.0:30102` (OTLP / Ingest Hub in `~/Viettel/NetworkTracing`).
- **Ingest NodePort**: `http://<node-ip>:30103/api/ingest` (Plain HTTP / non-SSL NodePort entrypoint for legacy C++ shippers such as `nt-ship-cpp` / `nt-sniff-cpp`; verified on public node `129.150.59.233:30103`).
- **Ingress HTTP NodePort**: `http://<node-ip>:31561` (Cluster Ingress-Nginx plain HTTP NodePort routing `/api/ingest`, `/api/agent/stats`, `/api`, and `/` without TLS; verified on public node `129.150.59.233:31561`).
- **Cluster APM & Elasticsearch Services**:
  - `tmp-elk-svc` (NodePort `9200:32073/TCP`, ClusterIP `10.97.180.119:9200`): Elasticsearch 7.17.24 holding APM indices (`apm-*-transaction-*`, `apm-*-metric-*`, `apm-*-span-*`, `apm-*-error-*`). Wired directly to `tracescope-worker` and dashboard on `http://127.0.0.1:32073`.
  - `apm-server` (NodePort `10.99.87.70:8200` -> NodePort `32765`): Ingestion gateway daemon streaming APM data into Elasticsearch.
- **Lightweight Monitoring Stack (`light-mon`)**:
  - Namespace: `monitoring`
  - Release: `light-mon` (Chart: `prometheus-community/kube-prometheus-stack` via Helm with `--skip-crds -f values-lightweight.yaml`, Revision 5)
  - Configuration: `values-lightweight.yaml` (ephemeral emptyDir, 2d retention, Alertmanager/nodeExporter/kubeStateMetrics disabled, Grafana NodePort `32080` with admin/admin, `additionalScrapeConfigs` scraping `https://trace.n2d.id.vn:443/metrics`).





---

## 2. Architecture & Components

### Backend (`backend/`)
- **API Server & Static Mount** (`backend/main.py`):
  - Framework: FastAPI with CORS middleware.
  - Serves built React SPA from `frontend/dist` at `/` and `/assets`.
  - Endpoints:
    - `GET /api/v1/health`: Health status and demo mode indicator.
    - `GET /api/v1/overview`: System health, KPIs (current RPS, error rate, p95 latency, active services/principals, anomaly counts), comparative series, and top rankings.
    - `GET /api/v1/services`, `GET /api/v1/services/{service}`: Service inventory, detailed health metrics, operations breakdown, callers, downstream dependencies, instances.
    - `GET /api/v1/principals`, `GET /api/v1/principals/{principal}`: Identity behavior explorer, target services, operations, callers, hourly activity profile.
    - `GET /api/v1/topology`: Directed service dependency graph with edge details (traffic, p95, error rate, top principals, top operations).
    - `GET /api/v1/topology/bandwidth`: Byte-aware system or filtered bandwidth rate and five-minute series for the dashboard, read from worker-owned `metric_buckets` in both storage modes. The worker materializes byte totals in both 1-minute and 5-minute buckets.
    - `GET /api/v1/anomalies`, `GET /api/v1/anomalies/{id}`, `PATCH /api/v1/anomalies/{id}`: Anomaly incident lifecycle management, explainability card data, probable root cause, blast radius.
    - `GET /api/v1/traces`, `GET /api/v1/traces/{trace_id}`: Distributed trace search & multi-tier span waterfall hierarchy.
    - `GET /api/v1/blast-radius/{service}`: Upstream caller graph traversal, affected principals & operations.
    - User Intelligence & Incidents:
      - `/api/v1/users` inventory/profile subresources, `/api/v1/user-changes`, `/api/v1/user-changes/{id}/review` (operator overrides with scope and expiry), `/api/v1/user-graph`, `/api/v1/user-analytics`.
      - Bounded Security Incidents: `GET /api/v1/incidents`, `GET /api/v1/incidents/{id}` with capped family scores, 15m windows, 30m idle close, and 24h lifetime.
    - `POST /api/v1/ingest`, compatibility alias `POST /api/v1/ingest/traces`, and old-kernel shipper alias `POST /api/ingest`: bounded OTEL/ELK or NetworkTracing `{node, events[]}` ingestion with credential sanitization, automatic `Content-Encoding: gzip` / magic-byte decompression with HTTP 400 rejection on corrupted payloads, and transaction-atomic `X-Batch-Id` deduplication (HTTP 200 `{"ok": true, "duplicate": true}` on replay, zero duplicate database insertions). Concurrent uploads enter the bounded coalescing writer; saturation returns HTTP 429 plus `Retry-After: 1`, and HTTP 200 is sent only after durable ClickHouse commit.
    - **Ingest Batch Deduplication** (`backend/app/repositories/ingest_batch_repository.py`): Defined in `backend/clickhouse_migrations/001_initial.sql` as the `ingest_batches` table with in-memory LRU cache and automatic 7-day pruning.
    - **High-TPS Ingest Writer** (`backend/app/services/ingest_writer.py`): A background writer thread coalesces concurrent requests for up to 5 ms / 50,000 records into batched ClickHouse INSERTs, bounds admission to 256 queued requests, writes trace rows and batch IDs durably, exposes queue/commit counters through `GET /api/v1/ingestion/status`, and shuts down cleanly with the FastAPI lifespan. Per-request rollup launches were removed; the existing `tracescope-worker` performs analytics on its 60-second cadence.
    - **Agent Stats** (`backend/app/api/agent_stats.py`): Oldkernel Agent Statistics Protocol v1 receiver.
      - `POST /api/agent/stats`: Accept a 16 KiB-bounded agent health sample. Validates `schema_version=1`, `type=agent_stats`, required fields, bounded `status` enum (`ok`/`degraded`), and bounded `reasons` enum. Idempotent: duplicate `(node, instance_id, sequence)` returns HTTP 200 `{"accepted": false}`. Spec: `~/Viettel/NetworkTracing/oldkernel/AGENT-STATS-PROTOCOL.md`.
      - `GET /api/agent/stats[?node=<name>]`: Latest health sample per node (or specific node).
      - `GET /api/agent/stats/{node}[?instance_id=<id>]`: Node latest summary status, known instance list, and runtime metadata.
      - `GET /api/agent/stats/{node}/history[?limit=N&instance_id=<id>]`: Recent history samples for a node (optionally filtered by instance_id, default 120, max 2880 ≈ 24 h at 30-second interval) with flat metrics unwrapped for instant time-series plotting.
      - `DELETE /api/agent/stats/{node}[?instance_id=<id>]` & `DELETE /api/agent/stats/{node}/{instance_id}`: Delete a specific agent instance or an entire agent node and its historical telemetry records. Returns HTTP 200 on success, HTTP 404 if not found.
    - Legacy aliases: `/api/v1/accounts`, `/api/v1/dashboard/summary`, `/api/v1/dashboard/series`, `/api/v1/events`, `/api/v1/ingestion/status`.
- **Domain Models** (`backend/app/models/`):
  - `trace.py`: `NormalizedTrace` with canonical observation fields (`principal_id`, `environment`, `identity_source`, `auth_result`, `auth_evidence`, `caller_resolution_method`, `caller_confidence`, `operation_key`, `original_client_ip_trusted`, `dedup_key`).
  - `incident.py`: `Incident`, `OperatorOverride`.
  - `aggregate.py`: `MetricBucket`.
  - `baseline.py`: `BaselineMetric`.
  - `topology.py`: `ServiceEdge`, `PrincipalServiceEdge`, `TopologyNode`, `TopologyEdge`.
  - `anomaly.py`: `AnomalyEvent` (clean model without unobtained `instance` or dummy attributes), `AnomalyReason`.
- **Repository Layer** (`backend/app/repositories/`):
  - `db_context.py`: ClickHouse connection context with a narrow SQLite-compatibility DB-API adapter (dialect translation confined here).
  - `trace_repository.py` & `elasticsearch_trace_repository.py`: Normalized trace batch insert, query, and search. `list_traces` filters out non-trace metric documents and requires `trace.id`, preventing unresolvable synthetic IDs from appearing in the UI. `get_trace` includes `_id` fallback in search.
  - `aggregate_repository.py`: Rollup storage, time-series query, KPI summaries.
  - `topology_repository.py`: Edge materialization, topology graph generation, caller/dependency traversal.
  - `baseline_repository.py`: Baseline storage and retrieval by hour-of-day/day-of-week.
  - `anomaly_repository.py`: Anomaly event querying, lifecycle patching (open, investigating, resolved, suppressed). Coalesces contiguous open anomaly occurrences for identical dimensional signatures within 15 minutes, preserving root incident ID, extending `last_seen`, tracking `occurrences` count, and calculating `duration_mins` in metadata via ClickHouse `ReplacingMergeTree ORDER BY id`.
  - `principal_repository.py`: Principal rankings and comprehensive behavioral profiling.
  - `user_repository.py`: User inventory, fingerprint profiles, timelines, explainable changes, graph, analytics, operator review actions, and incidents query.
  - `agent_stats_repository.py`: Agent health sample storage — upserts `agent_stats_latest` (one live row per node+instance), appends to `agent_stats_history` (idempotent via UNIQUE on `(node, instance_id, sequence)`), prunes history to 2880 rows/node, and provides atomic `delete_node` purging.
  - `clickhouse_migrator.py`: Versioned migration orchestrator (`001` through `005_system_telemetry_retention.sql`) and system retention manager (`configure_system_telemetry_retention`, `truncate_system_logs`). Enforces bounded 3-day TTL on system logs (`text_log`, `query_log`, `processors_profile_log`, etc.) and 7-day TTL on `error_log` to prevent disk exhaustion.
- **Analytics & Detection Services** (`backend/app/services/`):
  - `behavioral_engine.py`: Canonical identity normalization, detector readiness, multi-layer baselines, bounded incident lifecycle, capped family scoring (Origin cap 35, Access cap 40, Activity cap 35, Identity mapping cap 30, Authentication cap 45), 7-question explainability cards, and new behavioral/auth detectors (`OPERATION_MIX_SHIFT`, `CALLER_PRINCIPAL_SWITCH`, `TARGET_FANOUT_SURGE`, `SOURCE_FANOUT_SURGE`, `PRINCIPAL_RATE_SURGE`, `AUTH_FAILURE_BURST`, `FAILURE_THEN_SUCCESS`, `SOURCE_IDENTITY_FANOUT`, telemetry quality gates).
  - `normalization.py`: Normalizes OTel / ELK payloads, extracts canonical `enduser.id` / `labels.enduser.id` / `user.id` as principal username, derives trusted IP / proxies via environment-configurable subnets and IP lists (`OTEL_TRUSTED_PROXIES`, `OTEL_KNOWN_LOAD_BALANCERS`, `OTEL_KNOWN_F5`, `OTEL_KNOWN_LB`, `OTEL_KNOWN_REVERSE_PROXY`) supporting CIDR matching without blind hardcoding of private RFC 1918 subnets (preventing internal Kubernetes pod IPs from being marked as load balancers), extracts WSSE usernames with case preservation, sets canonical `operation_key` (`Service/operation`), and maps decoupled `auth_result` / `auth_evidence`.
  - `aggregation.py`: Computes 60s and 300s rollups with exact p50/p95/p99 percentiles.
  - `baseline.py`: Computes rolling median and MAD across dimensions from eligible five-minute windows, excluding detected service traffic, latency, and error incident intervals.
  - `anomaly_detection.py`: Detectors: traffic_spike, traffic_drop, latency, error_rate, new_service_edge, new_principal_edge, unusual_access (behavioral shift by learned user or IP accessing a new endpoint never seen in baseline, or 401/403 authorization failure bursts without hardcoded strings), unusual_time (off-hours activity for established accounts), and user_new_source_ip / ip_new_user.
  - `blast_radius.py`: Recursive caller traversal and impact calculation.
  - `root_cause.py`: Probable origin heuristic.
  - `principal_extractor.py`, `principal_relationships.py`, `principal_profile.py`, `principal_baseline.py`, `principal_change_detector.py`, `principal_graph.py`, `principal_analytics.py`: incremental credential-behavior derivation from the existing sanitized `traces` table.
- **Maintenance & Migration Scripts** (`backend/scripts/`):
  - `generate_10day_demo_dataset.py`: Generates a complete 10-day dataset with 13 enterprise personas and randomized abnormalities; writes request/response byte totals and sample counts into both 1-minute and 5-minute `metric_buckets`, plus 5-minute interactive topology relationship rollups and ClickHouse trace retention.
  - `rebuild_aggregates.py`: Recomputes all rollups, edges, baselines, and detects anomalies.
  - `import_json.py`: Imports NDJSON, JSON arrays, and Elasticsearch hits.
- **Lifecycle Script** (`run_server.sh`):
  - `./run_server.sh {start|stop|restart|status}` managing tmux sessions `tracescope-30102` and `tracescope-worker`.

### Frontend (`frontend/`)
- **Tech Stack**: React 19, Vite, TypeScript, Tailwind CSS, TanStack Query, Recharts, HTML5 Canvas.
- **Design System & Typography**: Clean, matte, non-glossy glanceable observability monitor design system.
  - Typography: 100% standard font scaling, 12px Recharts axis ticks, crisp typography hierarchy.
  - Surfaces: Grafana-style matte canvas (`#0b0c0e`), panels (`#111217`), raised controls (`#181b1f`), compact side rail (`#111217`).
  - Zero Glossy Effects: Eliminated all `radial-gradient` ambient sheens, `backdrop-blur` frosted glass filters, and glowing `shadow-[0_0_...` neon halos.
  - Borders: Crisp, flat borders `#2a2d30` with stronger control borders `#34373b`; no card shadows.
  - Multi-Accent Palette:
    - Healthy / successful: Green (`#73bf69`).
    - Primary telemetry / informational: Blue (`#5794f2`).
    - Warning / elevated: Orange (`#ff9830`).
    - Failure / critical: Red (`#f2495c`).
    - Secondary series: Purple (`#b877d9`); baseline/grid: muted gray (`#303236`).
    - Entity identity accents are separate from status: User/Credential lavender (`#b877d9`), Service blue (`#5794f2`), API teal (`#56b9a8`), and IP neutral gray (`#a7a9ab`). Use them only on relationship labels, icons, paths, topology nodes, and selected entity context; operational status colors remain independent. For non-human principals, the primary call path is `Caller Service → Target Service → API / Operation`, with the observed credential attached as evidence on that call rather than drawn as the initiating actor. Only confirmed human principals may be presented as a User actor. Color alone must never carry role meaning, and related Trace evidence is required to confirm exact causality or credential forwarding.
  - Multi-Color Visualizations: Restrained low-opacity fills, compact legends, HTTP status mapping (2xx green, 3xx blue, 4xx orange, 5xx red), and semantic topology nodes/edges without specular sheen.
- **Built Output**: `frontend/dist` served directly by FastAPI on port 30102.
- **Navigation & Pages**:
  - `Overview` (`/`): Behavior-focused operational dashboard with compact TPS, bandwidth, unresolved-attention, and grouped Service/User footprint cards. Main TPS/baseline line chart sits beside a service traffic-share donut; a weekday-by-hour episode-start heatmap reveals change clusters. Important changes and Service/User lists follow below.
  - `Topology` (`/topology`): Interactive seven-day map of observed service relationships. It opens with last-24-hour activity; the five-minute slider selects a specific historical slice. Connections observed in the selected window are blue, previously observed connections are muted and dashed with their last-seen time, and selected paths are thin yellow lines without inline guide labels. Initial service node positions use the measured canvas dimensions and keep cards separated; after layout, manual dragging is unrestricted and starts from card content while excluding the expand control. The right inspector is a compact floating panel with activity KPIs, a small trend, and expandable metrics/evidence/IP sections; its entity links navigate to Service, API, or User pages. The Elasticsearch metric worker reads explicit caller service fields from transaction metadata and stores them in ClickHouse metric buckets; observed materialized edges fill gaps where transactions lack caller names. Clicking graph nodes and scroll-box rows selects and highlights relationships in place without navigation. The former `/users/:principal/topology` route redirects to User Activity.
  - `Changes` (`/changes`, `/changes/:id`): Unified operator model over service anomaly signals and User behavior-change signals. Detector facts are correlated into episodes, then evaluated separately as `EXPECTED`, `CHANGED`, `NEEDS ATTENTION`, or `CRITICAL`. Legacy `/anomalies` and `/anomalies/:id` routes redirect into this experience. Every global episode card exposes `View details` and `Investigate`; Investigate opens the episode detail directly at its LLM investigation section. Detail pages include metric diff, relationship path, timeline, evidence, abnormality reasons, Trace links, operator decisions, and the LLM investigation UI.
  - `Services` (`/services`, `/services/:name`): Service catalog, operation percentiles, caller graphs, and instances. Service Detail places compact clickable KPI cards above a configurable TPS line chart; selecting Requests, Error rate, P95 latency, or Bandwidth overlays its available series while TPS remains plotted. The shared KPI card and TPS chart labels follow the User Activity style, and bandwidth uses its measured bucket series.
  - `Principals` (`/principals`, `/principals/:name`): Identity behavior explorer, target services, operations, callers, and hourly activity profiles.
  - `Traces` (`/traces`, `/traces/:id`): Trace explorer with filters and multi-tier interactive waterfall visualization.
  - `User Intelligence`:
    - `User Directory` (`/users`): Searchable principal inventory with live stats, risk level badges, sort controls, and launcher into user workspace.
    - `User Workspace & Layout` (`/users/:principal`): Compressed 2-row Grafana-style sticky header saving 100-150px vertical height above the fold, featuring identity, environment, active/baseline/behavior-state badges, inline metrics ribbon (`Requests`, `Services`, `APIs`, `Callers`, `IPs`, `Window`), compact `Switch ▾` account button, and embedded `Activity` / `Changes` navigation tabs:
      1. `Activity` (`/users/:principal/activity`): Dense User activity workspace with an integrated `Behavior | Access` segmented control. Behavior has 4 clickable KPI Stat panels (TPS, Error rate, P95 latency, Bandwidth) and a TPS vs Baseline chart that always retains both TPS lines. Clicking another KPI overlays its configured metric lines on a permanently reserved right axis; clicking TPS clears the overlay while right-side TPS values remain visible. The plot bounds and TPS path do not shift across selections, and the TPS scale runs from zero to the actual positive peak of its plotted series, including fractional peaks below 1 TPS (with a 1 TPS fallback only for all-zero data). Dense TPS windows keep the original worker five-minute metric buckets for data/state logic while the line chart renders at most 450 source points using min/max-preserving selection; lines are linear with animation disabled. The hover readout maps the cursor time back to the nearest original five-minute bucket. Missing bandwidth bytes leave the chart on TPS without a warning beneath it. A 100% non-error versus failed request outcome chart sits beside it on wide screens, and the active-hour heatmap occupies the row below. Hovering either chart updates a shared time-bucket readout with worker aggregate metrics and outcome counts. The former Baseline-vs-current and Normal Footprint panels were removed. Access uses an optimized 3-column `Selected IP (25%) → Service (35%) → API (40%)` board titled `Access for {principal}`, with the selected principal retained in context and Caller Service evidence appearing in the selected relationship panel when worker IP rollups exist.
      2. `Changes` (`/users/:principal/changes`): Episode-based change view with a consistent Needs attention / All / Reviewed workflow and compact readable cards. `/users/:principal/changes/:episodeId` is the single investigation surface: deterministic summary, before-vs-now comparison, timeline, evidence, related Trace link, inline LLM analysis, and source-scoped operator decisions in one vertical flow. Evaluation state (`Changed`, `Needs attention`, `Critical`) is displayed separately from workflow state (`Open`, `Monitoring`, `Resolved`). The former `/users/:principal/investigations` route is a compatibility redirect into Changes or the selected Change detail AI section.
    - Global Feeds & Analytics: `/user-changes`, `/user-graph`, `/user-analytics`, `/incidents`.
  - `Infrastructure`: `Agent Fleet` (`/agent-stats`) and `Agent Drilldown` (`/agent-stats/:node`) with interactive time-series dashboards.
  - **TPS chart invariant**: `/services/:name`, API detail routes, and every `/users/:principal/*` workspace route render scoped TPS first. Activity satisfies this through its default Behavior segment; Access is the only separate internal view on the same route. Activity's worker metric buckets expose non-error and failed request counts for its percentage view.
  - Global Search in header: Search services, principals, or jump directly to trace waterfall by ID.
  - Entity navigation uses `frontend/src/entityRoutes.ts` and `EntityLink.tsx` for canonical Service, API, User, and Change routes across active pages. The topology graph and relationship lists remain selection controls; their side detail panel contains the entity navigation links. Investigation results show a concise explanation, evidence, and next steps; source-derived entity links are created by the backend, while run state, evidence IDs, model details, alternatives, and history stay in collapsed Technical details.
  - **Localization (i18n)**: Canonical Vietnamese UI copy across active pages, charts, tables, cards, and modals with persistent language switcher (`🇻🇳 VI` / `🇬🇧 EN`) defaulting to Vietnamese. DevOps/product vocabulary remains English where it improves operator recognition (`Service`, `API`, `User`, `TPS`, `Latency`, `Trace`, `IP`, `Baseline`, `Agent`, and protocol/database names); surrounding explanatory copy is translated.

---

- **Dashboard behavior-focused layout (2026-09-28)**: Overview keeps TPS/baseline as its main line graph and replaces latency/error/bandwidth charts with a service traffic-share donut and a weekday-by-hour heatmap of episode starts inside the selected window. Compact top cards show TPS, bandwidth, unresolved attention episodes, and grouped Service/User footprint. Counts disclose loaded episode coverage; the heatmap supports focus/hover readouts, uses the selected timezone, and counts each episode once. Change/service/user lists remain below. Latency/error metrics remain available in service detail and Grafana.

- **Dashboard sparklines and toolbar dropdowns (2026-09-28)**: TPS and bandwidth KPI cards reuse the shared MetricCard sparklines. The top-bar Filters panel uses native selects for Service, Operation, Account, Environment, Group, and Module, loading observed options only while expanded. Operation choices come from the selected service; changing or clearing Service clears Operation. URL-selected values are preserved even when absent from the loaded options. Service/account options are bounded at 500 and disclose the cap; loading/error/empty states and retry controls are provided.

- **Compact Changes triage (2026-09-28)**: `/changes` uses dense responsive rows with evaluation/workflow state, localized change title, affected entity, exact signal-type chips, one before/after metric, last-seen time, and detail/investigation actions. Compact count tabs replace large KPI cards. The change-type dropdown matches all signal/evidence detector types in each episode, including secondary correlated types. Subject/search/AI/type/sort/view persist in the URL and survive detail-return navigation. Local filtering and 25-row pagination operate on up to 500 loaded episodes, with loaded/total coverage disclosed.

## Dashboard time-series revision (2026-09-28)

- Overview no longer renders the FleetTriage service table; service-level triage remains available on `/services` and `/changes` as appropriate.
- The secondary dashboard panel now renders shared HTTP 4xx/5xx error-rate lines from `dashboard/series`, replacing Fleet Signals. The weekday/hour behavior-change heatmap is promoted to a full-width panel directly beneath TPS and error rate.
- The dashboard remains focused on fleet-level trends and investigation entry points rather than duplicating the service catalog.
- Validation pending after this revision.

## Fleet-scale dashboard revision (2026-09-28)

- Overview replaces the service-share donut with a compact fleet signal summary and full-width `FleetTriage` table. Designed for 200+ observed services, it loads at most 500 and renders 10 rows per page with service search, anomaly/error filters, and priority/TPS/error/max-bucket-P95/name ordering. Service links preserve the selected time filters.
- Default ranking is open anomaly, error rate, then average TPS. Labels reflect the API semantics: open anomalies are current open flags, TPS is the selected-window average, and latency is maximum bucket P95. No-open-anomaly is explicitly not an availability/SLO guarantee; missing metrics display a dash.
- Unresolved attention/critical changes precede the secondary weekday/hour heatmap and user list. The TPS/baseline chart and KPI sparklines remain. Loaded coverage and caps are disclosed.
- Validation: production build and diff check passed; all seven live dashboard API requests returned 200. Chromium verified a mocked 240-service fleet, pagination/search/filter/sort, empty search, and 1440px/390px layouts without document overflow or page errors. No backend changes or restart.

## 3. Rules & Operational Guidelines
- **Rule xHatsu**: Always start responses with `"I HAVE FOLLOW THE RULE xHatsu DEFINED FOR ME BY DEFAULT"`.
- **POSIX Shell**: Strictly POSIX `/bin/sh` compliant. Never use bashisms (`[[ ]]`, `local`, `declare`, `array[i]`, `&>`, etc.).
- **Timers**: Set a schedule timer before executing fast commands to detect/prevent freezing.
- **Kubernetes**: NEVER execute any `kubectl` command.
- **Testing**: Always test API endpoints and scripts to confirm functionality across cases.
- **State Management**: Keep `AGENTS.md` and `STATE.md` updated with system state, access instructions, and guides.

---

- **Test Suite**: 197/197 tests passed in an isolated temporary-database harness (`.venv/bin/python -m pytest tests/ -q`); production data is never mutated by tests:
  - Canonical `enduser.id` extraction from Elasticsearch APM documents across top-level, nested, labels, attributes, and search fields (`tests/test_elk_enduser_normalization.py`).
  - Worker metrics exposure via `/metrics` Prometheus endpoint (`tests/test_prometheus_metrics.py`).
  - F5 BIG-IP unresolved IP handling without guessing client IP (`observed_ip = F5 IP`, `effective_client_ip = "unavailable"`, `ip_resolution = "load_balancer_unresolved"`), with explicit infrastructure IP categorization (`known_f5`, `known_lb`, `known_reverse_proxy`, `known_nat`) and suppression of IP behavioral signals on LBs (`tests/test_f5_lb_normalization.py` and `tests/test_user_ip_anomalies.py`).
  - Anonymous Traffic Isolation (`user = -anonymous-`): isolated from user directory, user baselines, user risk scoring, and active accounts, while retaining 100% telemetry volume for TPS, RPS, latency, and capacity (`tests/test_user_ip_anomalies.py`).
  - Detection of unauthorized / sensitive unusual access patterns (`unusual_access` / "Truy cập Bất thường") in `tests/test_user_ip_anomalies.py`.
  - Unified Helm global image tag resolution and component overrides (`tests/test_deployment_topology.py`).
  - LLM diagnostic investigation subsystem unit, integration, and security tests (`tests/test_llm_investigation_*.py`) including `_parse_object` resilience across markdown code fences, `<think>` tags, and reasoning token limits.
  - Unit & domain tests in `tests/test_analytics.py`, `tests/test_api.py`, `tests/test_ingestion.py`.
  - Ingestion batch deduplication and gzip decompression tests in `tests/test_batch_dedup_and_gzip.py`.
  - High-concurrency request coalescing, atomic concurrent deduplication, bounded-queue backpressure, and retryable HTTP 429 tests in `tests/test_ingest_writer.py`.
  - Comprehensive behavioral API tests in `tests/test_behavioral_api.py`.
  - Canonical identity normalization, realm removal, multi-layer baselines, detector readiness, capped family scoring, and bounded incident lifetime tests in `tests/test_identity_normalization_and_incidents.py`.
  - Dedicated IP anomaly and novel user on host tests in `tests/test_user_ip_anomalies.py`.
  - F5 BIG-IP load balancer SNAT, XFF, X-Real-IP, and IP spoofing rejection in `tests/test_f5_lb_normalization.py`.
  - Reference compatibility and WSSE ingestion tests in `tests/test_reference_compat.py` and `tests/test_wsse_ingestion.py`.
  - Service boundary, workload splitting, and topology tests in `tests/test_service_boundaries.py`, `tests/test_split_workloads_integration.py`, and `tests/test_deployment_topology.py`.
  - Host/probe agent trace isolation in ClickHouse (`tests/test_agent_traces_only.py`).
  - System telemetry log retention and truncation (`tests/test_system_retention.py`).
  - Compact AggregatingMergeTree principal readiness summary (`tests/test_principal_readiness_summary.py`).
  - Aggregation worker start time cutoff, historical data bypass, checkpoint fast-forwarding, and Elasticsearch sync initial page range filtering (`tests/test_worker_start_time.py`).
  - Change episode evaluation and aggregation tests (`tests/test_changes_episode_evaluation.py`).
  - All 22 code review findings verified and documented in `FIX_REPORT.md`.
- **End-to-End Curl & JS Safety Test Suite**: 50/50 tests passed (`sh backend/scripts/curl_test_all_pages.sh`).
  - Tested all 21 SPA routes (including `/changes`, `/agent-stats`, `/agent-stats/:node`, and user workspace sub-routes) with HTTP 200 and valid HTML shell bundle delivery.
  - Tested 29 backing APIs against frontend TypeScript contracts via `backend/scripts/validate_js_safety.py` and curl.
  - 0 JavaScript crash risks identified (zero undefined `toFixed`, `length`, or `map` vulnerabilities).
- **Frontend Lint/Build**: Passed (`tsc -b && vite build` built in 10.9s with 0 errors).
  - Design tokens (`--canvas: #0b0c0e`, `--surface: #111217`, `--surface-raised: #181b1f`, `--border: #2a2d30`, `--border-strong: #34373b`, `--grid: #303236`, `--blue: #5794f2`, `--green: #73bf69`, `--orange: #ff9830`, `--red: #f2495c`, `--radius-panel: 3px`) implemented across all components.
  - Application Shell: compact rail (Dashboard, Explore [Services, Users, Topology], Changes, Investigate [Traces], System [Agent Fleet]), dynamic `TraceScope / {Current Entity}` header, global search, and explicit Refresh button.
  - User Overview tab: TPS vs Baseline (1.6fr) beside 2x2 KPI grid (1fr: Requests, Bandwidth, Error Rate, P95 Latency), Important Changes episodes, paired Error/Latency charts, Bandwidth time series, and Source IP evidence table. Standalone TPS chart removed from Overview.
  - Global Dashboard (`Overview.tsx`): 1. Health KPI summary strip, 2. Main TPS chart beside "What changed", 3. Top Services & Top Users tables, 4. Recent Changes episodes.
  - ServiceDetailPage & ApiDetailPage: Structured operational layout (Header, TPS vs Baseline, Health metrics, APIs/Operations, Users, Latency/Errors, Dependencies, Changes episodes, Representative Traces).
- **Playwright Real Browser E2E Suite**: 15/15 pages passed (`python3 backend/scripts/test_pages_playwright.py`).
  - Headless Chromium navigated to all 15 existing and User Intelligence SPA routes.
  - Full React hydration, query resolution, and visual canvas/chart rendering verified.
  - 0 unhandled `pageerror` exceptions, 0 React render crash boundaries, and 0 console error failures.
- **Port 30102 Status**: Online and healthy, listening on all interfaces (`http://0.0.0.0:30102`).
- **High-TPS Hub Deployment (2026-09-11)**: Bounded/coalescing writer is active on `:30102`; live ingestion status reported `writer_alive=true`, queue `0/256`, successful durable commits, zero failed requests, and atomic duplicate replay. Full isolated test suite passed 74/74 and the live curl/JavaScript contract suite passed 42/42 after deployment.
- **Testbed State**: Cleanly wiped testbed state via `backend/scripts/reset_testbed.py`. ClickHouse analytical tables (0 traces, 0 metric buckets, 0 principals, 0 anomalies) and Elasticsearch APM indices (`apm-*`) reset to clean state ready for new ingestion. System telemetry logs truncated. Dashboard online and healthy on port 30102.
- **Data Correctness**: Anomaly APIs filter and investigate by telemetry observation windows, expose measured bucket/baseline sample counts and MAD ranges, return matching trace evidence, and include metadata-associated principals. User scores count distinct evidence types once and explicitly distinguish learning from established baselines.
- **WSSE UsernameToken Attribution**: Active `/api/ingest` and `/v1/traces` ingestion safely normalize namespaced WSSE usernames and store only `principal_name` with `auth_scheme=wsse`. OASIS 2004 plus legacy 2002/07, 2002/12, and 2003/06 `secext` namespaces are supported; malformed, unnamespaced, DTD/entity, oversized, and invalid usernames remain anonymous. SOAP bodies, passwords/digests, and nonces are never persisted or logged. Verified live on `:30102` with HTTP 200 and trace/API/database evidence.
- **Java WSSE OTLP Fixture**: `/tmp/wsse-java-service` accepts bounded SOAP on
  `0.0.0.0:18080` and exports real spans to this active hub's `/v1/traces`.
  No OpenTelemetry SDK dependencies are installed, so it is explicitly a
  minimal/manual OTLP HTTP JSON exporter. It sends only sanitized
  `wsse.username` plus non-sensitive service/HTTP metadata; the hub strips the
  source identity attribute after deriving `principal_name` and
  `auth_scheme=wsse`.
- **PCAP Authentication & Username Inspection Script**: Tested and verified ([`backend/scripts/inspect_pcap_auth.py`](file:///home/ubuntu/Viettel/OtelTrace/backend/scripts/inspect_pcap_auth.py) and copied to [`~/Viettel/Data/inspect_pcap_auth.py`](file:///home/ubuntu/Viettel/Data/inspect_pcap_auth.py)).
  - Zero third-party dependencies (pure standard Python `struct`, `base64`, `re`, `gzip`).
  - Supports standard pcap, nanosecond pcap, gzip-compressed pcap, Linux cooked v1/v2, Ethernet.
  - Extracts and isolates usernames from HTTP Basic Auth (`Authorization: Basic <base64>`), WSSE SOAP XML (`<wsse:Username>...</wsse:Username>`), and WSSE HTTP Headers (`X-WSSE`).
  - Verified on real production captures: `Data/tcpdump_10.240.147.247.pcap` (218 WSSE tokens, user `product`), and `NetworkTracing/pcap/tcpdump_10.240.147.249.pcap` (149,263 packets, 12,593 auth occurrences, 80 distinct usernames including `cm2.0`, `sale`, `vtp`, `myViettel`, `pm_mini_app`, `chatbot`).
- **Unauthenticated Traffic (`-anonymous-`) Architecture & Codex Review Guide**: Saved in [`docs/PLAN_ANONYMOUS_USER_HANDLING.md`](file:///home/ubuntu/Viettel/OtelTrace/docs/PLAN_ANONYMOUS_USER_HANDLING.md) and [`docs/GUIDE_PLAN_CODEX_REVIEW.md`](file:///home/ubuntu/Viettel/OtelTrace/docs/GUIDE_PLAN_CODEX_REVIEW.md).
- **Redesigned Data Generator & Modular Anomaly / User Behavior Generator (`~/Viettel/Data` & `backend/scripts`)**:
  - `anomalies.py`: Modular object-oriented Anomaly & User Behavioral Change Generator defining scenarios aligned with TraceScope's 8 core detectors and User Intelligence behavioral engine (`principal_relationships.py`):
    - **Core Observability Detectors**:
      1. `traffic_spike`: 3.5x RPS surge on `order-service` (10.0h - 11.5h).
      2. `traffic_drop`: 85% drop on `notification-service` (15.5h - 16.5h).
      3. `latency_blowout`: 8.0x tail latency blowout on `payment-service` `chargeCard` (13.0h - 14.5h).
      4. `cascading_failure`: Root 5xx outage on `billing-service` propagating 502 to callers (19.0h - 20.5h).
      5. `new_service_edge`: Architectural drift with rogue dependency `customer-service` -> `payment-service` (15.0h - 24.0h).
      6. `new_operation`: Novel endpoint `AdminService/debugDump` on `admin-service` (16.0h - 24.0h).
    - **User Intelligence Behavioral Changes (`principal_relationships.py` & `README.md`)**:
      7. `user_first_seen`: New identity `guest_checkout_partner` first observed after historical 75% baseline cutoff (18.5h - 24.0h) (`USERNAME_FIRST_SEEN`, score: 10).
      8. `user_new_caller`: Caller expansion with `vtp` arriving from unexpected caller `apex-inventory-service` (18.5h - 24.0h) (`NEW_CALLER`, score: 30).
      9. `user_new_source_ip`: Source IP expansion with `sale` connecting from anomalous foreign IP `185.220.101.5` (19.0h - 24.0h) (`NEW_SOURCE_IP`, score: 20).
      10. `user_new_target`: Target expansion with `chatbot` accessing sensitive target `apex-admin-service` (18.0h - 23.5h) (`NEW_TARGET`, score: 25).
      11. `user_new_operation`: Operation expansion with `pm_mini_app` executing novel endpoint `OrderService/cancelReservation` (18.5h - 24.0h) (`NEW_OPERATION`, score: 15).
      12. `user_unusual_time`: Off-hours interactive access by human identity `sale` at 02:00-04:30 UTC (`UNUSUAL_TIME`, score: 10).
      13. `user_dormant_reactivation`: Account `cm2.0` silent for 19 hours, then bursting at 20.0h-23.5h (`DORMANT_REACTIVATED`, score: 40).
      14. `credential_abuse`: Identity `myViettel` connecting from foreign IP `185.220.101.5` via `customer-service` (21.0h - 24.0h).
  - `generate_traces.py`: High-performance generator integrating authentic production PCAP identities, 9 multi-tier enterprise services, diurnal traffic curves, W3C TraceContext causality, and strict 75/25 historical bootstrap partitioning. Supports `--days <N>` (e.g. `--days 15`), `--anomalies <all|none|list>`, `--list-anomalies`, and outputs detailed ground-truth injection summaries.
  - `send_traces.py`: High-performance streaming ingestion tool supporting HTTP batch POSTing (`--mode http`) and fast direct ClickHouse batch writes (`--mode direct`, auto-tuned 5,000 batch size).
- **15-Day 2,000,000 Data Point Dataset Generated**:
  - File: `/home/ubuntu/Viettel/Data/otel_elk_traces_2m.jsonl.gz` (495.27 MB).
  - Preview: `/home/ubuntu/Viettel/Data/otel_elk_sample_preview.json` (100 sample records).
  - Timespan: Exactly 15 days (360.0 hours) from `2026-08-24 07:29:10 UTC` to `2026-09-08 07:29:12 UTC` (ending today right now).
  - Injected Ground Truth: 5,366 traffic spikes, 429 traffic drops, 772 tail latency blowouts, 1,737 cascading 5xx failures, 3,369 architectural drift calls, 769 novel operation calls, and 353,049 user behavioral change transactions across all 8 User Intelligence scenarios.
- **Oldkernel Agent Package & Bootstrap Server (Port 30105)**:
  - **Canonical Source of Truth**: The real `oldkernel` code (C++ sniffer, shipper, supervisor, scripts, Makefiles) canonically resides in `~/Viettel/NetworkTracing/oldkernel`. The deployment files reside in `~/Viettel/NetworkTracing/bundle`.
  - **Bootstrap Distribution Server**: Dedicated bootstrap and bundle distribution server resides in `~/Viettel/OtelTrace/bootstrap` (port 30105).
  - **Symlink Architecture**: `~/Viettel/OtelTrace/oldkernel -> ~/Viettel/NetworkTracing/oldkernel` and `~/Viettel/OtelTrace/bundle -> ~/Viettel/NetworkTracing/bundle` ensure single-source-of-truth integrity while packaging executes cleanly from `OtelTrace/bootstrap`.
  - **Universal Fleet Package (`bundle.tar.gz`)**: Packaged with both modern eBPF and real oldkernel agent code (`oldkernel/` containing `install-firstrun-el68.sh`, `nt-sniff-cpp`, `nt-ship-cpp`, `nt-sniff.py`, `nt-ship.py`, supervisor, and resource guards).
  - **Installer Auto-Delegation (`bundle/install.sh`)**: Automatically detects kernel floor (< 5.5) or `--oldkernel` flag and delegates to the packaged oldkernel installer.
  - **Bootstrap Daemon**: Managed directly via `run_server.sh` alongside TraceScope API (`:30102`).
- **Presentation Layer Migration (RPS to TPS)**: Standardized all user-facing throughput units, metrics, tooltips, chart legends, and comparison tables across the React frontend and API responses (`/users/{principal}/investigations`, `/anomalies`) from RPS / `req/s` to TPS / `tps` without breaking underlying database schemas or compatibility.
- **Topology API Connection Focus**: The topology canvas renders service-to-service wires by default. Selecting an expanded API overlays only that API's observed caller-service connections; clearing the selection or selecting another object removes those contextual API wires. The bounded endpoint is `GET /api/v1/topology/services/{service}/api-connections?api=...`.
- **Topology Fast Travel Search**: The full-page topology search finds services, APIs, and users across the seven-day slider horizon. Choosing a result jumps to its latest five-minute observation, expands its ancestry, centers the canvas card, and opens the matching detail inspector.
- **Topology Selection Layering**: Selected topology cards are promoted above all other canvas cards, while selected relationship wires render last in the SVG layer so overlapping objects do not obscure the active selection.
- **JavaScript Safe Integer Precision & Anomaly ID Guard**:
  - `deterministic_anomaly_id` (`anomaly_repository.py`) uses `(raw_hash % 9_000_000_000_000_000) + 1` to guarantee newly generated anomaly IDs strictly fit within JavaScript `Number.MAX_SAFE_INTEGER` ($2^{53} - 1 = 9,007,199,254,740,991$), preventing IEEE-754 precision loss and trailing-zero rounding in web browsers.
  - `get_anomaly`, `update_status`, and `anomaly_users` implement automatic float64 ULP tolerance fallback ($\pm 4096$) for any IDs $> 9 \times 10^{15}$, ensuring legacy or bookmarked URLs resolve accurately.
  - Database reset executed via `backend/scripts/reset_testbed.py` (truncated ClickHouse analytical tables, deleted Elasticsearch APM indices, truncated system telemetry logs).
- **Behavioral Change Events Deduplication (`principal_change_events FINAL`)**:
  - Enforced ClickHouse `FINAL` modifier across all `principal_change_events` queries in `UserRepository` (`list_changes`, `summary`, `analytics`, `service_users`, `graph`), ensuring `ReplacingMergeTree` collapses duplicate rows inserted across periodic micro-batches.
  - Added client-side defensive deduplication by fingerprint/key in `UserChangesTab.tsx`.
- **24-Hour Authentic PCAP Dataset Ingestion to ELK & ClickHouse (2026-09-17)**:
  - Tool: `/home/ubuntu/Viettel/Data/generate_pcap_to_elk.py`
  - Ingested 25,000 authentic transaction documents directly into Elasticsearch NodePort `:32073` (`apm-7.17.24-transaction-000001`, 8.9 MB) derived from production PCAP captures (`tcpdump_10.240.147.249.pcap` & `tcpdump_10.240.147.247.pcap`).
  - Realistic Gaussian latency distributions (p50: 25ms-120ms, p95: 80ms-220ms), authentic PCAP identities (`cm2.0`, `sale`, `myViettel`, `vtp`, `chatbot`, `cc2.0`, `product`, `cyber_space`, etc.), realistic status codes (97.5% 200, 1.5% 4xx, 1% 5xx), and 4 realistic scenarios (payment tail latency degradation, sale service traffic spike, product service error rate surge, novel caller/principal switch).
  - Streamed into ClickHouse `traces` (25,073 rows), 46,831 metric buckets (1m and 5m), 2,726 baseline metrics, 6,940 principal baselines, 121 principal change events, 16 security incidents, and 168 detected behavioral anomalies.
  - Verified with 100% pass on curl & JS contract safety test suite (48/48 tests passed across all 20 SPA routes and 28 backing APIs).
- **Anomaly Detail Incident Time Horizon Line Graph Fix (2026-09-18)**:
  - Fixed blank/missing line chart on `/anomalies/:id` (e.g. anomaly `6130971176347858`).
  - Backend `GET /api/v1/anomalies/{anomaly_id}` now accepts time range query parameters (`from`, `to`, `start`, `end`), allowing custom inspection windows matching global time picker filters.
  - Backend enriches `series` points with canonical millisecond `timestamp_ms` (`bucket_start * 1000`), computed `rps` / `tps` (`requests / 60.0`), `actual` values mapped according to anomaly metric type (latency p95, error rate %, or rps/tps), and `expected` baseline values.
  - Frontend `Anomalies.tsx` AnomalyDetailPage passes global filter time parameters to the query and maps `chartData` with defensive fallbacks (`timestamp_ms`, `requests`, `rps`, `p95_ms`, `http_5xx_rate`, `actual`, `expected`).
- **Reference**: Refer to `STATE.md` for full endpoints, features, and run guides.

---

## 4. Kubernetes Workload Split (2026-09-11)

- **Role-aware application**: `backend.app.application.create_app()` builds the
  backwards-compatible `all` app, the traffic-only `ingest` app, or the
  `agent-stats` lifecycle/reporting app. Entrypoints are `backend.main:app`,
  `backend.ingest_main:app`, and `backend.agent_stats_main:app`.
- **Stateless edge workloads**: Kubernetes starts 3 ingestion pods (HPA 3–12)
  and 2 agent pods (HPA 2–6). They mount no data volume. Ingestion pods perform
  decompression, parsing, credential sanitization, and normalization; agent pods
  validate protocol payloads and serve latest/detail/history/deletion contracts.
- **Storage-owner service boundary**: both edge roles use
  `OTEL_STORAGE_OWNER_URL=http://tracescope-storage:8000` and an
  `OTEL_INTERNAL_API_TOKEN`. Authenticated `/internal/v1/*` operations are
  excluded from OpenAPI. Storage errors retain retryable 429/503 behavior.
- **ClickHouse single store**: the single-replica `tracescope-clickhouse`
  StatefulSet owns the ReadWriteOnce data PVC. Application roles (storage API,
  ingest, agent-stats, worker) are stateless and connect over HTTP 8123;
  network/RWO-only applies to the ClickHouse volume.
- **Idempotency**: trace rows and `X-Batch-Id` remain transaction-atomic in the
  storage owner's coalescing writer. Agent `(node, instance_id, sequence)`
  acceptance is now one atomic insert, avoiding check-then-write races across
  multiple edge pods.
- **Routing and operations**: one Ingress preserves all public paths and routes
  ingestion, agent, and UI/query traffic to separate ClusterIP Services. Probes,
  requests/limits, PDBs, HPA resources, ConfigMap wiring, and a Secret template
  are under `deploy/k8s/`.
- **Build and migration**: `deploy/docker/Dockerfile` provides `api`, `ingest`,
  `agent-stats`, and `worker` targets. The storage pod init container exclusively
  owns migrations; runtime containers set `OTEL_RUN_MIGRATIONS=false`.
- **Runbook and validation**: `deploy/k8s/README.md` documents backup/restore,
  rollout, rollback, storage requirements, secrets, build commands, and risks.
  `deploy/k8s/validate_manifests.py` checks the single-PVC-owner invariant without
  contacting a cluster. Never run `kubectl` from this repository automation.

---

## 5. ClickHouse Persistence & Storage Architecture

- **Architecture Overview**: TraceScope has migrated its primary persistence layer to ClickHouse (`http://127.0.0.1:8123`, default database `tracescope`).
- **Database Engine & Driver**:
  - Python driver: `clickhouse_connect` HTTP client with thread-local client caching and connection lifecycle management in `backend/app/repositories/db_context.py`.
  - Schema & Migrations: `backend/clickhouse_migrations/001_initial.sql` defining 35 tables with `ReplacingMergeTree` engines for mutable entity sets, microsecond monotonic default IDs (`toUnixTimestamp64Micro(now64(6))`), and tracked via `schema_migrations`.
- **Data Parity & Migration**:
  - Offline migration copied 351,936 rows across 35 tables with 100% exact row parity (script and SQLite source purged 2026-09-11 after verification).
- **ClickHouse DB-API Compatibility Adapter (`backend/app/repositories/db_context.py`)**:
  - Literal escaping & binding: `_convert_placeholders_and_bind` translates `?` to literal-formatted values using `format_query_value(val, timezone.utc)`, avoiding `%` format collisions with Python format specifiers.
  - `ClickHouseRow`: Mimics `sqlite3.Row` with dictionary mapping, tuple access, sequence slicing (`row[1:5]`), and automatic unqualified column name mapping (e.g. `p.principal_name` accessible as `principal_name`).
  - Expression translations:
    - Scalar `MAX(a, b)` / `MIN(a, b)` -> `greatest(a, b)` / `least(a, b)`.
    - SQLite `strftime('%H', ts/1000, 'unixepoch')` -> `formatDateTime(toDateTime(intDiv(ts, 1000)), '%H')`.
    - `GROUP_CONCAT(col)` -> `arrayStringConcat(groupArray(toString(col)), ',')`.
    - `UPDATE` -> `ALTER TABLE ... UPDATE ... SETTINGS mutations_sync = 1`.
    - `DELETE` -> `ALTER TABLE ... DELETE ... SETTINGS mutations_sync = 1`.
    - `PRAGMA table_info` -> `DESCRIBE TABLE`.
    - `cursor.lastrowid`: simulated via `SELECT max(id) FROM {table}` for autoincrement parity.
- **Verification Suite**:
  - Pytest Suite: 197/197 tests passed across all test modules in `tests/` in an isolated test database harness (`test_pytest_<id>`).
  - End-to-End Curl & Safety Suite: 50/50 checks passed (`sh backend/scripts/curl_test_all_pages.sh`), covering all 21 SPA routes and 29 backing API endpoints with 0 JavaScript crash vulnerabilities.
  - Active Testbed Dataset: Clean 10-user enterprise hybrid dataset (184,896 historical 1m & 5m metric buckets injected directly for Days 0–23, 8,489 full raw traces for the active 7-day window synchronized across Elasticsearch `apm-7.17.24-transaction` and ClickHouse `traces`, 2,382 baselines, 145 anomaly events, 570 behavioral change events, 10 distinct user identities with dedicated abnormalities). Generated via `backend/scripts/generate_30day_demo_dataset.py`.

---

## 6. Helm Chart Design & Topology Modes (`deploy/helm/tracescope/`)

- **Production Helm Chart**:
  - Located at `deploy/helm/tracescope/` with `Chart.yaml` (v0.2.6), comprehensive `values.yaml`, and modular templates.
  - App pod named `tracescope-app-0` (StatefulSet `tracescope-app`), rendered with simplified `values.yaml` `app.image:` configuring `migrate`, `api`, and `analytics-worker` in one place with image tag `app-0.2.6`.
  - Ingestion workload runs `ingest-0.2.6` with HPA (3–12 replicas).
  - Supports full **Distributed Mode**, **Consolidated / Merged Modes**, and **Elasticsearch / ELK Mode**:
    - **Default Managed Topology (3-Tier)**: `ui.enabled: false` (UI merged into API) and `agentStats.enabled: false` (agent telemetry merged into API). Reduces deployment overhead from 5 workloads (9–21 pods) down to 3 workloads (5 pods: ClickHouse, Storage API+UI+Worker, and Ingest HPA pool).
    - **Full Distributed Mode**: Enable `ui.enabled: true` and `agentStats.enabled: true` for independent scaling pools.
    - **External ClickHouse Mode**: `clickhouse.enabled: false` connects to external ClickHouse clusters via `clickhouse.host` and `clickhouse.password`.
    - **Elasticsearch / ELK Mode**: `storage.backend: elasticsearch` routes application trace queries directly to Elasticsearch/ELK clusters (`elasticsearch.url`, `elasticsearch.index`, `elasticsearch.apiKey`), while retaining host/agent telemetry in ClickHouse.
  - **Docker Images Published**:
    - `xhatsu101/tracescope:app-0.2.6` (digest: `sha256:63ae3efc8c2ae7fddba3082fff2d29f0e6c0e9ae1d1c1726a2f9529c85a4a8cf`)
    - `xhatsu101/tracescope:ingest-0.2.6` (digest: `sha256:11e96722ca50c919ccebebeadece3c458c7dbc58670facb6b314ea8166e9b861`)
  - **Verification**: Verified via `helm lint` (0 errors) and `helm template` across all topology permutation cases. Docker containers verified with smoke tests (`APP_SMOKE_OK`, `INGEST_SMOKE_OK`).

---

## 7. 2-Image Architecture & Build/Push Pipeline

- **Consolidated 2-Image Architecture**:
  - Image 1 (`Target: api`): Main App image (`xhatsu101/tracescope:app-<version>`), serving FastAPI analytics queries, bundled React 19 UI (`/app/frontend/dist`), schema migration init container, agent-stats, and background analytics worker via container command override.
  - Image 2 (`Target: ingest`): Ingest image (`xhatsu101/tracescope:ingest-<version>`), serving high-throughput trace batch ingestion with HPA horizontal scaling.
  - Database: Official upstream `clickhouse/clickhouse-server:24.8` (no custom build required).
- **Automated Build & Push Script (`scripts/build_and_push.sh`)**:
  - 100% POSIX `/bin/sh` compliant script (symlinked to `deploy/docker/build_and_push.sh`).
  - Robust directory discovery: searches upwards for `deploy/docker/Dockerfile` so it executes seamlessly from any working directory or symlink location.
  - Outputs strictly 2 images: `xhatsu101/tracescope:app-<version>` and `xhatsu101/tracescope:ingest-<version>`.
  - Supports token replacement templates (`{image}` and `{tag}`).
  - Supports `--dry-run` (`-d`) and `--no-push` (`-n`) flags.
  - Aligned with Helm chart (`deploy/helm/tracescope/values.yaml`): `agentStats.enabled: false` (consolidated into storage-0) and configured to use `xhatsu101/tracescope:app-0.2.0` if enabled.

---

## 8. Live Production User Data Push & End-to-End Verification (2026-09-12)

- **Production Target**: `https://trace.n2d.id.vn`
- **Shipper Execution**: `/tmp/push_to_production.py` streamed 250,000 spans from `/home/ubuntu/Viettel/NetworkTracing/data/otel_traces_2m.jsonl.gz` in 500 OTLP `resourceSpans` batches (Gzip-compressed, 3 threads, persistent keep-alive, unique `X-Batch-Id`).
  - Throughput: 4,449.3 spans/sec (8.9 batches/sec), 56.19s duration.
  - Data transfer: 228.49 MB uncompressed -> 24.58 MB compressed (9.3x compression ratio).
  - Reliability: 100% acked (250,000 / 250,000), 0 rejected, 0 429s, 2 transient 5xx cleanly retried and committed.
- **User-Analysis End-to-End Verification**:
  - `otlp_parser.py` consumed `enduser.id` semantic conventions into `principal_name` dimensions in ClickHouse.
  - `/api/v1/users`: Populated with all 8 named identities (`minh.ngoc`, `linh.pham`, `mai.tran`, `khanh.vu`, `duong.nguyen`, `quang.bui`, `hong.dang`, `thao.trang`).
  - `/api/v1/users/minh.ngoc`: Exact match against ground truth on all microservice request counts (`session-cache`: 6186, `api-gateway`: 3514, `notification-service`: 2874, `catalog-service`: 1925, `cart-service`: 1335).
  - `/api/v1/user-graph`: 28 nodes (10 users, 17 targets) and 188 directed dual-layer access edges.
  - `/api/v1/user-analytics`: All 10 ranking categories populated.
  - `/api/v1/user-changes`: 625 change events across 4 detector families (`USERNAME_FIRST_SEEN`, `NEW_SOURCE_IP`, `NEW_TARGET`, `NEW_OPERATION`) complete with 7-question explainability cards.
  - `/api/v1/incidents`: 18 bounded security incidents with capped family scoring (Score 75 across all 8 named users).
  - ClickHouse trace lookups: Spot checks on multi-tier spans across all users returned HTTP 200 with waterfalls spanning up to 16 microservices.
- **Identified Production Infrastructure Limit**:
  - ClickHouse worker aggregation (`aggregate_traces`) hit container memory ceiling: `Code: 241. DB::Exception: Memory limit (total) exceeded: would use 1.81 GiB, maximum: 1.80 GiB`.
  - Recommendation: Increase ClickHouse container RAM limit to >= 4 GiB and implement bounded time-window chunking (max 24h slices) in `aggregate_traces`.
- **Deliverable**: Full verbatim test report stored at `USER_DATA_PUSH_TEST_REPORT.md`.

---

## 9. Release 0.2.2 Deployment Preparation & Preflight Fixes (2026-09-14)

- **Release Version**: `0.2.2`
  - Chart metadata: `deploy/helm/tracescope/Chart.yaml` bumped to `version: 0.2.2`, `appVersion: "0.2.2"`.
  - Application version: `backend/app/application.py` FastAPI `version="0.2.2"`.
  - Image tags: `xhatsu101/tracescope:app-0.2.2` and `xhatsu101/tracescope:ingest-0.2.2` built and pushed to Docker Hub.
    - App Digest: `sha256:721acd2ef5e7a35be9f1e3879c8daba5be728bc8bd57b481c624665da8052cbf`
    - Ingest Digest: `sha256:d03d3e20549bc44a43d8f2b3e993c07105c29f3760034bad27e1e0b38c0d05af`
- **Security & Secret Provisioning**:
  - Independent cryptographically random tokens (64 chars, urlsafe base64) generated and embedded into `deploy/helm/tracescope/values.yaml` under `secrets.internalApiToken` (`1Ioi...(64 chars)`) and `secrets.apiKey` (`XOyx...(64 chars)`).
  - Redaction enforced across all logs, stdout, and reports.
  - Public mutation endpoints (`/api/ingest`, `/v1/traces`) now enforce authentication when deployed with chart defaults.
  - Ingress blocks external access to `/internal/*` via nginx `location ^~ /internal/ { return 404; }`.
  - Dockerfile cleaned: removed `ENV OTEL_CLICKHOUSE_PASSWORD=""`, eliminating Docker `SecretsUsedInArgOrEnv` warnings.
- **ClickHouse Headroom & Retention**:
  - ClickHouse memory raised in `values.yaml`: requests `2Gi`, limits `4Gi`.
  - Schema Migration 004 created (`backend/clickhouse_migrations/004_live_table_retention.sql`): applies 30-day TTL on `traces` and fixed 90-day TTL on `metric_buckets`.
- **Configuration Parity**:
  - Nine backend environment variables mapped into `values.yaml` and ConfigMap templates (`configmap.yaml` and `edge-configmap.yaml`): `OTEL_INGEST_MAX_BATCH_BYTES` (33554432), `OTEL_AGGREGATION_MAX_MEMORY_USAGE` (1073741824), `OTEL_AGGREGATION_EXTERNAL_GROUP_BY_BYTES` (268435456), `OTEL_AGGREGATION_SHADOW_ENABLED` (true), `OTEL_AGGREGATION_CUTOVER` (false), `OTEL_BASELINE_CADENCE_SECONDS` (300), `OTEL_BASELINE_SERIES_BUDGET` (100), `OTEL_ANOMALY_WINDOW_BUDGET` (100), `OTEL_ANALYTICS_STAGE_BUDGET_SECONDS` (55).
  - Used `{{ int .Values.config.<key> | quote }}` to prevent scientific notation formatting in rendered templates.
  - Production origin `https://trace.n2d.id.vn` added to `config.corsOrigins`.
- **Validation**:
  - `helm lint deploy/helm/tracescope`: 0 warnings, 0 failures, exit code 0.
  - `helm template tracescope deploy/helm/tracescope --namespace tracescope > /tmp/rendered-0.2.2.yaml`: exit code 0.
  - Full test suite: 123/123 tests passed in isolated test harness (`123 passed in 201.64s`).
  - Report deliverable: `DEPLOY_FIX_REPORT.md` written to repository root.

---

## 10. Release 0.2.2 Commit & Secret Isolation (2026-09-14)

- **Secret Isolation**:
  - Real secrets (`secrets.internalApiToken` `1Ioi...(64 chars)` and `secrets.apiKey` `XOyx...(64 chars)`) moved from `deploy/helm/tracescope/values.yaml` into gitignored `deploy/helm/tracescope/values-secrets.yaml`.
  - Added `values-secrets.yaml` to `.gitignore`.
  - `values.yaml` retains empty string defaults with explicit comments pointing to `values-secrets.yaml`.
  - Updated operator runbook in `DEPLOY_FIX_REPORT.md` §4 and §5 to supply `-f deploy/helm/tracescope/values-secrets.yaml`.
  - Verified `helm template` passes with `-f values-secrets.yaml` and fails without it due to template validation guard.
- **Repository Cleanup**:
  - Confirmed database purge (ClickHouse sole datastore; no local SQLite/DuckDB files).
  - Cleaned untracked junk directories (`.agents`, `.codex`).
  - Flagged ambiguous task briefs for retention.
- **Verification**:
  - 123/123 tests passed cleanly (`123 passed in 260.88s`).
  - Verified 0 hits on secret leak scan across all Git history.

---

## 11. Overview Fix & User-Centric Anomalies Overhaul (2026-09-15)

- **Overview Page & API Health**:
  - Root cause of broken Overview page resolved: `filters_model` in `backend/app/application.py` had rigid `start: datetime, end: datetime` requirements with no defaults and no parameter alias matching frontend's `from`/`to`, throwing HTTP 422 `Field required`.
  - Added `_parse_time_param` to parse ISO strings, epoch milliseconds, epoch seconds, and datetimes, with rolling 3h defaults.
  - Storage repository dashboard queries (`dashboard_summary`, `dashboard_series`, `rankings`, `heatmap`) redirected to live `metric_buckets` and `traces` in ClickHouse instead of legacy empty tables.
  - Added `_detect_clickhouse_host()` probe in `backend/config.py` to auto-discover ClickHouse on local or cluster IPs.
  - Enhanced `queryString` in `frontend/src/api.ts` to output `start`, `from`, `end`, and `to`.
  - Added defensive fallback default in `frontend/src/pages/Overview.tsx` for `summary.data`.
- **User-Centric Anomalies Overhaul**:
  - `frontend/src/pages/Anomalies.tsx`:
    - Summary KPI cards: Total Findings, Identity-Centric Findings, Impacted Users count, Top Offending Identity with direct link to user profile.
    - Perspective switcher: `All Findings` | `User & Identity Centric` (cyan-accented) | `Service & Fleet` (violet-accented).
    - Real-time search filter across user, IP, service, operation, or detector type.
    - Table column: Prominently attributes identities with clickable user badge linking to `/users/:user` (with User icon and external link) and Source IP badge.
    - Anomaly Detail Page: Hero "User Intelligence & Identity Context" card with user investigation action buttons, and enhanced "Related Users" panel with traffic share bars and behavioral changes flags.
    - Fixed Minified React error #31 by creating `getEntityName` to safely parse both string and object `{name, requests, error_rate}` shapes in `blast_radius.affected_principals` and `direct_callers`.
- **Validation**:
  - Playwright Chromium Real Browser Test Suite (`python3 backend/scripts/test_pages_playwright.py`): All 15/15 real browser pages passed in headless Chromium with 0 unhandled JS errors, 0 failed API requests, and 0 ErrorState renders.
  - Pytest Suite (`.venv/bin/python -m pytest tests/ -q`): All 139/139 unit and integration tests passed cleanly in 130s.
- **Kubernetes Deployment Invariants & Parity**:
  - `deploy/docker/Dockerfile`: Multi-stage build (`ui-builder` -> `api`, `ingest`, `agent-stats`, `worker`) tested with 100% clean TypeScript/Vite compilation.
  - In Kubernetes, `OTEL_CLICKHOUSE_HOST` is supplied via `tracescope-config` ConfigMap as `tracescope-clickhouse`. `backend/config.py` preserves explicit environment variables with zero probe delay.
  - `deploy/k8s/validate_manifests.py`: 17 documents across 10 resource kinds verified (0 errors).
  - Helm chart `deploy/helm/tracescope`: `helm lint` passes cleanly with `values-secrets.yaml`, and `helm template` renders valid Kubernetes manifests.
  - Strictly adherence to the constraint: never execute `kubectl` command.

---

## 12. 6 User-Centric Pages & Supporting Attribution Signal Architecture (2026-09-16)

- **6 User-Centric Operational Pages**:
  1. `User Overview` (`/users/:principal/overview`): *“Is this user behaving normally right now?”* — 8 KPI cards, 4 high-contrast line charts in a 2x2 grid (two lines, each line two cards: RPS vs base, error rate, p95, Abnormality Score Spike scaled with high RPS deviation where 10% off base = 10 pts, protected with a 0.5 req/s baseline significance floor to prevent sub-second traffic from inflating to 100 pts), mini change timeline, new relationship summary.
  2. `Activity & Performance` (`/users/:principal/activity`): *“Which Services used this identity, what did they call, and how did that traffic behave?”* — TPS vs Baseline first, compact operational KPIs, service-first relationship table and API drilldown, paired latency/status charts, with IP and normal-pattern data as secondary evidence.
  3. `Access & Topology` (`/users/:principal/topology`): *“Where was this principal observed?”* — IP-scoped relationship explorer whose primary call path is `Caller Service → Target Service → Operation`; a non-human principal is displayed as an observed credential attached to the call, while a confirmed human principal remains a User identity.
  4. `Behavior Changes` (`/users/:principal/changes`): *“What is different from the user’s normal behavior?”* — Deviation-only behavioral shifts, before vs now category distribution bars, and 7-questions explainability timeline.
  5. `Usage Patterns` (`/users/:principal/patterns`): *“When and how does this user normally operate?”* — 24h × 7d activity heatmap, target services distribution bars, operations distribution bars, and behavioral scope time series.
  6. `Anomalies & Investigations` (`/users/:principal/investigations`): *“What needs investigation?”* — Triage queue, trigger hypotheses, BEFORE vs NOW metrics comparison table, causal relationship chain, and operator review controls.
- **Supporting Attribution Signal Architecture (IP as Context)**:
  - **Core Model**: The telemetry aggregation key remains `principal × caller × target × operation`, but the UI must not imply that every principal initiated the request. For service/system/shared/integration credentials, show `Caller Service → Target Service → Operation` as the primary call path and attach the credential as observed authentication context. For `principal_type=human`, the principal may be labeled User. Exact propagation claims require supporting Trace evidence.
  - **IP Context**: Observed source IP is attached as supporting context (`observed_source_ip`, `effective_client_ip`, `source_ip_role`, `attribution_confidence`).
  - **Classification**: `classify_source_ip_role` categorizes IPs into `load_balancer`, `reverse_proxy`, `nat_gateway`, `service_ingress`, `client`, and `infrastructure` with `high`, `medium`, and `low` confidence.
  - **Incident Weighting**: Known/likely load balancers (`low` confidence) are suppressed or zero-weighted in incident scoring, while genuine client IPs are elevated.
  - **Selective Integration**:
    - Overview: Card 8 `Source IPs` with dashed border and `Secondary Attribution Context` pill.
    - Activity: Source IP filter dropdown with role pills (`Client` vs `Load Balancer`).
    - Topology: Pure behavioral path default; optional `[ ] Show network path (IPs / Proxies)` toggle to reveal intermediate network hops.
    - Changes: High-value novelties (`NEW_CALLER`, `NEW_TARGET`, `NEW_OPERATION`, `NEW_RELATIONSHIP`) prioritized over supporting network novelties.
    - Patterns: Known IPs baseline card as secondary attribution context.
    - Investigations: IP included as corroborating evidence with explicit role labels.
- **Validation**:
  - TypeScript & Vite build: 100% clean (`tsc -b && vite build`).
  - Curl & JS Safety Test Suite (`sh backend/scripts/curl_test_all_pages.sh`): All 48/48 tests passed (0 JS crash risks).
  - Playwright Chromium Real Browser Test Suite (`python3 backend/scripts/test_pages_playwright.py`): All 17/17 pages passed with 0 unhandled JS exceptions.
  - Pytest Suite: All 17 unit and behavioral normalization tests passed cleanly.

---

## 13. Deployment Artifacts & Multi-Platform Readiness (Helm, K8s, Docker) (2026-09-17)

- **Helm Chart (`deploy/helm/tracescope`)**:
  - Chart SemVer bumped to `0.3.0` (`Chart.yaml`).
  - Configured `llm:` block in `values.yaml` with `enabled`, `singleOwnerAck`, `baseUrl`, `model`, `responseMode`, `allowLoopbackHttp`, `contextTokens`.
  - Configured `secrets.llmApiKey` in `values.yaml` and `values-secrets.yaml`.
  - ConfigMap template (`templates/configmap.yaml`) and Secret template (`templates/secret.yaml`) cleanly map `OTEL_LLM_*` and `OTEL_LLM_API_KEY`.
  - Verified with `helm lint deploy/helm/tracescope/ -f deploy/helm/tracescope/values-secrets.yaml` (0 chart errors) and `helm template`.
- **Plain Kubernetes Manifests (`deploy/k8s/`)**:
  - `deploy/k8s/10-configmap.yaml`: Configured with `OTEL_LLM_*` environment variables and documentation.
  - `deploy/k8s/11-secret.example.yaml`: Configured with `OTEL_LLM_API_KEY` placeholder.
- **Docker & Docker Compose**:
  - `docker-compose.yml`: Parameterized `api` container with `OTEL_LLM_*` and `OTEL_API_KEY`, and `frontend` container with `VITE_API_KEY`.
  - `Dockerfile` & `deploy/docker/Dockerfile`: Standardized multi-stage container build supporting optional build-time frontend environment arguments (`VITE_API_KEY`, `VITE_API_URL`).

---

## 14. Investigation Route Auth Decoupling (2026-09-17)

- In `backend/app/api/investigations.py`, decoupled `investigation_auth` from mandatory `settings.api_key`.
- If `OTEL_API_KEY` is not set on the backend, `/api/v1/investigations/*` routes operate in open mode (matching the rest of the TraceScope telemetry endpoints), eliminating the `503 auth_unconfigured` barrier when deploying with public/edge-authenticated dashboards.
- If `OTEL_API_KEY` is configured, strict `X-API-Key` comparison via `hmac.compare_digest` is enforced as before (HTTP 401 on invalid/missing key).

---

## 15. Unified Global Helm Image Tag Resolution (`0.3.3`)

- **Helm Chart Bump**: `deploy/helm/tracescope/Chart.yaml` bumped to `version: 0.3.3` and `appVersion: "0.3.3"`.
- **Global Helper**: `deploy/helm/tracescope/templates/_helpers.tpl` added `tracescope.globalImageTag` helper.
- **Templates**: All component workloads (`storage-statefulset.yaml`, `ingest-deployment.yaml`, `agent-stats-deployment.yaml`, `ui-deployment.yaml`) default to the global image tag (`global.image.tag: "0.3.3"`).
- **Interchangeability**: Added explicit `command: ["uvicorn", "backend.ingest_main:app", "--host", "0.0.0.0", "--port", "8000"]` to `ingest-deployment.yaml` so the unified container runs any component role.

---

## 16. Build and Push Script Unified Image Tag Support (`scripts/build_and_push.sh`)

- **Root Cause Fix**: `scripts/build_and_push.sh` previously hardcoded `app-${VERSION}` and `ingest-${VERSION}` as tag suffixes, preventing creation of the base version tag `xhatsu101/tracescope:0.3.3` that Helm expects under `global.image.tag: "0.3.3"`.
- **Unified Build Target**: Main App build target (`--target api`) now tags both `xhatsu101/tracescope:0.3.3` and `xhatsu101/tracescope:app-0.3.3` (`-t $GLOBAL_IMAGE -t $APP_IMAGE`) and pushes both.
- **Flags Added**:
  - `--unified-only` (`-u`): Builds and pushes only the unified application image (`:0.3.3` and `:app-0.3.3`).
  - `--ingest-only`: Builds and pushes only the standalone ingest image (`:ingest-0.3.3`).
- **POSIX Compliant**: 100% standard POSIX `/bin/sh` syntax.
- **Verification**: Verified via `--dry-run` across all flag permutations and automated regression tests in `tests/test_deployment_topology.py` (27/27 passed).

---

## 17. Investigation Model UUID Parsing & Anomaly API Endpoints

- **Pydantic Strict Mode Fix**: Added `_coerce_uuid` validator to `InvestigationCreate.retry_of` (`backend/app/models/investigation.py`) so string UUIDs sent in HTTP JSON payloads are cleanly converted to `uuid.UUID` objects without raising strict model `ValidationError`.
- **Deduplication Behavior**: Without `retry_of`, `POST /api/v1/investigations` returns the existing cached run (`reused: true`). Supplying `retry_of: "<prev-run-id>"` initiates a new execution attempt with `retry_index = 1`.
- **Endpoints**:
  - Snapshot: `GET /api/v1/investigations/source?kind=anomaly_event&id=<id>`
  - Create/Retry: `POST /api/v1/investigations`
  - Get Status: `GET /api/v1/investigations/<run_id>`
  - History: `GET /api/v1/investigations?kind=anomaly_event&id=<id>`
- **Verification**: 14/14 LLM investigation unit tests passed; full test suite (168 tests) passed.

---

## 18. OpenTelemetry Collector Telemetry Metrics Schema Migration Fix

- **Issue**: OTel Collector Contrib pod failed during startup with:
  `'migration.MetricsConfigV030' has invalid keys: address, no need for metrics`
- **Root Cause**:
  1. OpenTelemetry Collector schema migration `MetricsConfigV030` deprecated `service.telemetry.metrics.address` in favor of Prometheus pull `readers`.
  2. Unquoted / uncommented text `no need for metrics` inside YAML dictionary was parsed as an invalid mapping key.
- **Resolution (`/home/ubuntu/agy/otel-obi/otel-collector.yaml`)**:
  - Replaced legacy `address: 0.0.0.0:8888` with valid schema:
    ```yaml
    service:
      telemetry:
        logs:
          level: info
        metrics:
          readers:
            - pull:
                exporter:
                  prometheus:
                    host: 0.0.0.0
                    port: 8888
    ```
  - For disabling collector internal metrics, use `level: none`.

---

## 19. Prometheus Exposition Metrics from Web Services

- **Module**: `backend/app/services/prometheus_metrics.py`
  - In-memory thread-safe `PrometheusMetricsRegistry` with pure ASGI `PrometheusMiddleware`.
  - Exposes standard web application metrics at `GET /metrics`:
    - `http_requests_total{method, handler, status}`: Request count per HTTP method, route, and status code.
    - `http_request_duration_seconds_bucket{method, handler, le}`: Latency histogram with standard duration buckets (`0.005` to `10.0s` and `+Inf`), plus `_sum` and `_count`.
    - `http_requests_in_progress`: In-flight active request gauge.
    - Process metrics: `process_resident_memory_bytes`, `process_cpu_seconds_total`, `process_start_time_seconds`, `process_uptime_seconds`.
    - Service info: `tracescope_service_info{version="0.3.3", role="...", backend="..."}`.
    - Ingest writer metrics: `tracescope_ingest_writer_queue_depth`, `tracescope_ingest_writer_alive`, `tracescope_ingest_writer_committed_total`, etc.
- **Cadence & Worker Integration**:
  - Web requests only update in-memory request counters and latency histograms.
  - Heavy database metrics (`total_spans`, `nodes_reporting`, `c_2xx`, `c_err`, `users_rpm`, `open_anomalies`) are **ONLY updated once per cycle by `backend.worker`** (`update_prometheus_metrics` stage).
  - Snapshot is saved to ClickHouse `checkpoints(source='worker_prometheus_metrics')` and `/tmp/tracescope_worker_metrics.json`.
  - Scraping `GET /metrics` never queries ClickHouse aggregations directly, serving the precomputed snapshot in microseconds.
  - Exposes `tracescope_worker_last_run_timestamp_seconds` and `tracescope_worker_cycle_duration_seconds`.
- **Verification**: Dedicated test suite in `tests/test_prometheus_metrics.py` (6/6 passed); worker integration verified via `python -m backend.worker --once`; full regression test suite passed (178/178 passed).

---

## 20. 30-Day Multi-Persona Demo Dataset & Behavioral Anomaly Cases

- **Generator Script**: `backend/scripts/generate_30day_demo_dataset.py`
  - Generates 38,734 realistic transaction traces across 30 days (`2026-08-19` to `2026-09-18`) spanning 10 distinct user personas.
  - Dual ingestion: Indexed into Elasticsearch `apm-7.17.24-transaction` at `http://127.0.0.1:32073` with canonical `enduser.id` and inserted into ClickHouse `traces`.
  - Rebuilt rollups (33,092 1m buckets, 23,265 5m buckets), baselines (2,967 median/MAD baselines), anomaly evaluations (327 anomaly events), and principal behavioral derivations (7 incidents, 11 principals).
- **10 User Personas & Anomaly Cases**:
  1. `alice` (Steady Golden Baseline): 6,003 traces across 30 days. Clean reference account with 0 security incidents.
  2. `bob` (Candidate Promotion): 5,062 traces. Accesses `billing-service` on Days 20–29, promoted to established baseline. `unusual_access` detected on initial transition.
  3. `charlie` (Traffic Spike & Rate Surge): 2,673 traces. Sudden 1,200 req burst in recent window vs baseline ~100–200 reqs (`traffic_spike` & `PRINCIPAL_RATE_SURGE`).
  4. `david` (Traffic Drop / Outage): 11,514 traces. Collapses from 400 req/day to only 2 requests in recent window (`traffic_drop`).
  5. `eve` (Latency Shift & Blast Radius): 2,321 traces. Latency blowout on `payment-service` to 950ms–1800ms (`latency` shift).
  6. `frank` (Error Rate Surge): 3,000 traces. 45% 5xx Internal Server Errors on `order-service` (`error_rate` critical).
  7. `grace` (Target Fanout Surge & New Edges): 2,696 traces. Sweeps 5 new target services (`auth`, `billing`, `payment`, `inventory`, `notification`) in 45m (`new_service_edge`, `new_principal_edge`, `TARGET_FANOUT_SURGE`, `unusual_access` x22, incident score 40).
  8. `heidi` (Unusual Access & Credential Shift): 2,365 traces. Switches caller to `api-client` and executes administrative billing actions (`unusual_access`, `OPERATION_MIX_SHIFT`, `CALLER_PRINCIPAL_SWITCH`, incident score 70 - High).
  9. `ivan` (Off-Hours Night Activity & Novel IP): 2,098 traces. Off-hours activity at 02:00–04:30 UTC (`unusual_time`) and novel external source IP `194.26.29.11` (`user_new_source_ip`, incident score 35).
  10. `judy` (Auth Attack & Novel User on Known IP): 132 traces. Credential brute-force / auth failure burst (`AUTH_FAILURE_BURST` with 130+ 401s, then `FAILURE_THEN_SUCCESS` 200 OK login) and novel user on known internal IP `198.51.100.50` (`ip_new_user`, incidents scored 60 and 55 - High).

---

## 21. Pure TPS & Historical Baseline Chart Refactor (Overview Dashboard)

- **Backend Fix (`backend/repository.py`)**:
  - Resolved `baseline_rps` duplication bug in `dashboard_series` where `baseline_rps` was set to `rps`.
  - Now queries `baseline_metrics` (`rps_median`) grouped by `(hour_of_day, day_of_week)` matching active filter (`service`, `account`, `operation`, or system-wide sum across services).
  - Also enriches `dashboard_summary` with `baseline_rps` and `baseline_tps`.
- **Frontend Refactor (`frontend/src/pages/Overview.tsx` & `frontend/src/i18n.tsx`)**:
  - Converted "Tốc độ Lưu lượng Định danh & Tỷ lệ Lỗi" panel into a clean, dedicated TPS and Historical Baseline chart: "Tốc độ Thông lượng Định danh & Chuẩn Lịch sử".
  - Subtitle updated to "Thông lượng giao dịch theo bucket 60s so với chuẩn lịch sử".
  - Action header shows `TPS: {observed_tps} • Chuẩn Lịch sử: {baseline_tps}`.
  - Eliminated the 5xx error rate line and secondary right Y-axis.
  - Tooltip formatted strictly for TPS (`{val} tps`).
  - Verified across 48 automated curl & JS safety tests.

---

## 22. Smooth Time-Series Generation & Prometheus Baseline TPS Exposition

- **Smooth Timestamp Generation (`backend/scripts/generate_30day_demo_dataset.py`)**:
  - Replaced high-variance Poisson `random.uniform()` with `generate_smooth_timestamps()`.
  - Partitions target time ranges into 60-second intervals and applies profile weighting (`diurnal` half-sine bell curve for daytime, `ramp_up` for Charlie's surge and Judy's brute-force, `ramp_down` for David's collapse, `bell` for Ivan's off-hours).
  - Micro-spaces events evenly within each minute with sub-second jitter, producing smooth, continuous 60s bucket curves without random zero drops or jagged spikes.
- **Prometheus Exposition (`backend/app/services/prometheus_metrics.py`)**:
  - Added `tracescope_observed_tps` and `tracescope_baseline_tps` gauge metrics to `GET /metrics`.
  - Computed during periodic worker cycle (or on-demand snapshot) with historical fallback, serving instant in-memory responses with zero database load on Prometheus scrapes.

---

## 23. 7-Day & 30-Day Global Time Range Redesign & Multi-Grain Downsampling

- **Global Time Range Controls (`frontend/src/App.tsx`)**:
  - Expanded the segmented control in the top navigation bar from `1h`, `3h`, `6h`, `24h` to include **`7d` (168h)** and **`30d` (720h)**: `[{ label: "1h", hours: 1 }, { label: "3h", hours: 3 }, { label: "6h", hours: 6 }, { label: "24h", hours: 24 }, { label: "7d", hours: 168 }, { label: "30d", hours: 720 }]`.
  - Dynamic active state detection: `Math.abs(rangeHours - hours) <= 1` prevents sub-minute floating point discrepancies from de-selecting the active preset button.
  - Added descriptive title tooltips (`Last 7d`, `Last 30d` / `7 ngày qua`, `30 ngày qua`) and localized labels in `frontend/src/i18n.tsx`.
  - Dynamic Rollup Indicator Badge: Dynamically switches between `60s rollup` (`<= 36h`), `5m rollup` (`36h < range <= 192h`), and `1h rollup` (`> 192h`).
- **User Topology Tab Presets (`frontend/src/pages/user/UserTopologyTab.tsx`)**:
  - Expanded topology view time filter buttons to `["5m", "1h", "24h", "7d", "30d", "all"]`.
  - Wired `7d` to `extra.start = now - 7 * 86400_000` and `30d` to `extra.start = now - 30 * 86400_000`.
- **Backend Dynamic Downsampling (`backend/repository.py` & `backend/app/repositories/user_repository.py`)**:
  - `backend/repository.py:dashboard_series`:
    - Auto-scales aggregation grain based on time window duration:
      - `<= 36h`: 60-second buckets (`grain_sec = 60`), preserves high resolution for 1h/3h/6h/24h.
      - `36h < duration <= 192h` (7 days): 5-minute buckets (`grain_sec = 300`, `intDiv(bucket_start, 300) * 300`), returns ~500–650 points.
      - `> 192h` (30 days): 1-hour buckets (`grain_sec = 3600`, `intDiv(bucket_start, 3600) * 3600`), returns ~250–350 points.
    - Prevents 43,200 raw bucket transfer bottlenecks, ensuring instant, lag-free chart rendering on 7d and 30d views.
  - `backend/app/repositories/user_repository.py:performance`:
    - Auto-adapts `bucket_ms` based on query horizon: 1h buckets for `> 192h`, 5m buckets for `> 36h`, and 60s/300s buckets for shorter intervals.
- **Chart Date Formatting for Multi-Day Ranges (`Overview.tsx`, `UserOverviewTab.tsx`, `UserActivityTab.tsx`)**:
  - Added multi-day date detection (`rangeHours > 24`).
  - XAxis tick formatters display `M/D HH:mm` when viewing 7d/30d ranges instead of ambiguous repeated time-only strings (`HH:mm`).
  - Tooltips display full locale timestamp (`Month Day, Year HH:mm:ss`) for unambiguous investigation context.
- **Testing & Verification**:
  - Vite production bundle built cleanly (`npm run build` exited code 0).
  - All 48 curl and JavaScript safety tests passed (`sh backend/scripts/curl_test_all_pages.sh`).
  - Verified 1h (60 points), 7d (627 points), and 30d (275 points) API series queries returning in sub-10ms.

---

## 24. Enterprise System Account Dataset & 100% Anomaly/Change Coverage

- **Database Clean Reset & Dual-Ingest Simulation**:
  - Script: `backend/scripts/generate_30day_demo_dataset.py`.
  - Wiped and re-indexed ClickHouse (`tracescope`) and Elasticsearch (`apm-7.17.24-transaction` on `127.0.0.1:32073`).
  - Transformed persona identities into realistic enterprise system/service accounts modeled after `~/Viettel/Data`:
    - `sys_erp_batch` (golden baseline diurnal jobs)
    - `api_gateway_sync` (candidate promotion to billing)
    - `svc_order_dispatcher` (traffic spike & rate surge)
    - `cron_reconciler` (traffic drop / complete service outage)
    - `paygate_settlement` (latency shift to 950ms+)
    - `billing_integrator` (45% 5xx server error rate surge)
    - `inventory_sync_worker` (target fanout surge across 5 microservices)
    - `sec_audit_collector` (unusual access & caller switch to CLI)
    - `infra_monitor_daemon` (off-hours night access & novel external IP)
    - `partner_b2b_client` (brute-force auth failure burst & novel user on known internal IP)
    - `legacy_backup_job` (dormant account reactivation after 25 days)
  - Trace Volume: 49,606 traces, 41,958 1m buckets, 14,281 5m buckets, 1,410 baselines.
- **100% Detector Coverage**:
  - **All 10 Anomaly Types** (`tracescope.anomaly_events`):
    1. `unusual_access`: 37 events
    2. `new_service_edge`: 25 events
    3. `new_principal_edge`: 22 events
    4. `unusual_time`: 20 events
    5. `traffic_drop`: 12 events
    6. `latency`: 4 events
    7. `error_rate`: 3 events
    8. `user_new_source_ip`: 2 events
    9. `traffic_spike`: 1 event
    10. `ip_new_user`: 1 event
  - **All 7 Behavioral Change Types** (`tracescope.principal_change_events`):
    1. `TARGET_FANOUT_SURGE`: 17
    2. `CALLER_PRINCIPAL_SWITCH`: 8
    3. `PRINCIPAL_RATE_SURGE`: 4
    4. `FAILURE_THEN_SUCCESS`: 2
    5. `AUTH_FAILURE_BURST`: 2
    6. `DORMANT_REACTIVATED`: 1
    7. `OPERATION_MIX_SHIFT`: 1
    (plus novelty detections: `NEW_RELATIONSHIP`: 35, `NEW_OPERATION`: 19, `NEW_TARGET`: 11, `NEW_CALLER`: 2, `NEW_SOURCE_IP`: 2, `USERNAME_FIRST_SEEN`: 1).
- **Anomaly Detail 24h Horizon & Time Toggles**:
  - Expanded `GET /api/v1/anomalies/{id}` with `window` parameter defaulting to 24h (`now - 86400`).
  - Added dynamic bucket sizing (`300s` for >12h horizons, `60s` for short horizons) and dynamic RPS calculation (`round(reqs / float(chosen_b_size), 3)`).
  - Frontend `frontend/src/pages/Anomalies.tsx`: Added interactive horizon toggle buttons (`1h`, `6h`, `24h`, `7d`) in panel action bar and date-time tick formatting (`MM/DD HH:mm`) on XAxis.
- **Defensive Float Sanitization (`NaN`/`Inf`)**:
  - Added `_clean()` helper in `backend/app/repositories/user_repository.py` to prevent ClickHouse `quantile(0.95)` from emitting `NaN` on 0-request outage windows, eliminating FastAPI 500 crashes.

---

## 25. Behavioral Scope Stability Redesign (Radar · Grouped Bar · Stability Trend)

- **Problem Addressed**:
  - The previous "Behavioral Scope Stability" component drew 4 overlapping stair-step lines (`stepAfter`) for integer dimensions (Targets, Operations, Callers, Source IPs) with small values (1 to 5) jumping on top of each other.
  - The chart was hard to read and did not clearly convey whether the identity was operating within authorized boundaries or performing privilege escalation.
- **Redesigned Multi-View Scope Component (`frontend/src/pages/user/UserPatternsTab.tsx`)**:
  - **Concept & Purpose**: Monitors the identity's credential footprint / scope envelope against its learned baseline across 4 dimensions: Target Services, Operations/APIs, Callers, and Source IPs. Protects against lateral movement, privilege escalation, and token hijacking.
  - **View 1: Radar Multi-Axis Chart (`scopeViewMode === 'radar'`, Default)**:
    - Recharts `<RadarChart>` rendering two overlapping multi-axis polygons:
      - **Historical Baseline**: Violet/Indigo shaded polygon (`#818cf8`) representing the learned normal perimeter.
      - **Observed Current**: Cyan (`#00f0ff`) or Amber (`#f59e0b`) polygon representing live observed scope.
    - An immediate glanceable visual: if Current is contained inside Baseline, the credential is strictly contained; if any axis extends outward, privilege expansion is detected.
    - Side-by-side **Stability Score Card** (`0% - 100%`) with containment badge (`ShieldCheck` for Contained / `AlertTriangle` for Expansion) and 4 dimension summary tiles showing baseline vs current numbers and delta tags (`+N new` or `Stable`).
  - **View 2: Grouped Bar Comparison (`scopeViewMode === 'bar'`)**:
    - Recharts `<BarChart>` displaying side-by-side bars for each of the 4 dimensions (Targets, Operations, Callers, Source IPs), comparing Baseline vs Current with clear numbers and distinct fills.
  - **View 3: Timeline Stability Trend (`scopeViewMode === 'timeline'`)**:
    - Recharts `<AreaChart>` with a single smooth gradient curve displaying the **Scope Stability Score (%)** over time with an 80% Safe Threshold reference line, completely replacing the 4 crisscrossing stair-step lines.
- **Testing & Verification**:
  - Vite production bundle built cleanly (`npm run build` completed in 19.1s).
  - All 48 curl and JavaScript safety tests passed (`sh backend/scripts/curl_test_all_pages.sh`).
  - All 17 Playwright Chromium headless browser pages passed (`python3 backend/scripts/test_pages_playwright.py`) with 0 unhandled JS exceptions and 0 render errors on `/users/:principal/patterns`.

---

## 26. Unknown & Unauthenticated Users Traffic Monitor (`/unknown-users`)

- **Architecture & Rationale**:
  - Implements the architectural design from `PLAN_ANONYMOUS_USER_HANDLING.md`: Isolates `-anonymous-`, `unknown`, and empty principal traffic from human and service account directories and risk ranking algorithms, preventing pseudo-user risk score distortion while maintaining 100% telemetry visibility.
- **Backend API (`GET /api/v1/unknown-users` & `GET /api/v1/users/unknown-traffic`)**:
  - Method: `UserRepository.unknown_users_analytics(start_ms, end_ms, limit=50)`
  - Returns comprehensive unauthenticated traffic KPIs:
    - `total_requests`: unauthenticated transaction volume and `traffic_percentage` of total estate ingress.
    - Status code breakdown: 2xx success, 401/403 authorization failures (`auth_fail_rate`), and 5xx server errors (`error_rate`).
    - Latency: exact `avg_latency`, `p95_latency`, and `p99_latency`.
    - Probed surface: `unique_targets`, `unique_operations`, `unique_sources`.
    - Time-series buckets (`series`) correlating throughput with auth failure bursts.
    - Top target services, top probed endpoints, and top source IPs with infrastructure roles (Load Balancer, Client IP, Reverse Proxy).
    - Recent 50 unauthenticated traces with HTTP statuses and direct links to multi-tier trace waterfall.
- **Frontend Page (`frontend/src/pages/UnknownUsers.tsx` -> `/unknown-users`)**:
  - Navigation: Prominently added to SideNav under `Identity & Access` (`[UserX, "Unknown Users", "/unknown-users"]`).
  - Routing: Wired to `/unknown-users`, with automatic redirects for `/users/-anonymous-` and `/users/unknown`.
  - Header in `UserDirectory.tsx`: Added an amber badge link `[Unknown Users & Public Traffic]` leading directly to the monitor page.
  - Interactive features: Search filter by service, operation, or IP; quick status tabs (`All`, `Auth Fails (401/403)`, `5xx Errors`); one-click jump to Trace Waterfall inspector.
- **Testing & Verification**:
  - All 50 curl tests passed in `sh backend/scripts/curl_test_all_pages.sh` (100% JS contract safe).
  - All 18 real browser pages passed in `python3 backend/scripts/test_pages_playwright.py` with 0 console errors and 0 unhandled exceptions.

---

## 27. Enterprise System Accounts Dataset Regeneration & 100% Detector Verification (2026-09-18)

- **Identity Renaming & Realism**:
  - Replaced legacy account names with 11 authentic enterprise and telecom infrastructure system accounts:
    1. `telecom_sync_svc`: Steady Golden Baseline (Days 0-29, 100% normal health).
    2. `vtp_express_dispatch`: Candidate Promotion (Days 20-29 promoted to established baseline).
    3. `pos_checkout_terminal`: Traffic Spike & Principal Rate Surge (Sudden volume ramp to 200+ req/5m).
    4. `billing_reconcile_job`: Traffic Drop / Outage (Daily 02:00-04:00 batch completely collapses to 0 req).
    5. `interbank_settlement_gw`: Latency Degradation & Blast Radius (Payment latency blowup to 950ms on `PayService/chargeCard`).
    6. `partner_sales_broker`: Error Rate Surge & Caller Switch (45% 5xx server errors on order creation + CustomerService calls).
    7. `enterprise_b2b_gateway`: New Service Edge + New Principal Edge + Target Fanout Surge (Sweeps 5 services in 45m).
    8. `secops_monitor_agent`: Unusual Access + Operation Mix Shift + Caller Switch (Switches to api-client & billing APIs).
    9. `sysadmin_deploy_agent`: Unusual Time (Off-Hours Night Rogue Access) + User New Source IP (Active 02:00-04:30 UTC from 185.220.101.5).
    10. `mobile_miniapp_gateway`: Auth Attack (Failure Burst then Success) + IP New User (130+ 401s then 200 OK on host 172.16.10.45, baseline host user `worker_health_monitor`).
    11. `audit_compliance_worker`: Dormant Reactivated (Active Days 0-1, silent 27 days, reactivated on Day 29).
    12. `unknown` / `-anonymous-`: Unauthenticated Public Traffic & Auth Probes (Populates the Unknown Users Monitor with 1,634 transactions and 401/403 authorization probes).
- **Database Metrics & Ground-Truth Coverage**:
  - Database Volume: 51,348 traces, 43,616 1m buckets, 14,538 5m buckets, 1,304 baselines, 820 anomaly events, 399 principal behavioral change events.
  - 10/10 Anomaly Detectors Active: `unusual_access` (48), `new_service_edge` (25), `new_principal_edge` (19), `error_rate` (10), `latency` (6), `unusual_time` (5), `traffic_spike` (4), `traffic_drop` (4), `ip_new_user` (1), `user_new_source_ip` (1).
  - All Behavioral Detectors Active: `NEW_IP_CALLER_PAIR` (2981), `NEW_OPERATION` (90), `UNUSUAL_TIME` (79), `NEW_TARGET` (73), `NEW_RELATIONSHIP` (31), `NEW_SOURCE_IP` (19), `TARGET_FANOUT_SURGE` (18), `NEW_CALLER` (11), `CALLER_PRINCIPAL_SWITCH` (8), `PRINCIPAL_RATE_SURGE` (4), `AUTH_FAILURE_BURST` (4), `FAILURE_THEN_SUCCESS` (2), `DORMANT_REACTIVATED` (1), `USERNAME_FIRST_SEEN` (1), `OPERATION_MIX_SHIFT` (1).
- **Verification Suites**:
  - `sh backend/scripts/curl_test_all_pages.sh`: 50/50 tests passed (0 JS crash risks).
  - `python3 backend/scripts/test_pages_playwright.py`: 18/18 real browser pages passed in headless Chromium with 0 unhandled exceptions.
  - `.venv/bin/python3 -m pytest tests/ -q`: 188/188 unit & integration tests passed cleanly in temporary test databases.

## 28. Interactive Service Topology (2026-09-18)

- `backend/clickhouse_migrations/008_interactive_topology.sql` defines bounded five-minute/current service, API, principal, and principal/IP topology tables, plus normalized source-IP/attribution and request/response byte columns on sanitized trace rows.
- `backend/app/repositories/interactive_topology_repository.py` reads those derived ClickHouse tables in ClickHouse mode and uses bounded server-side Elasticsearch aggregations in ELK mode; it never adds application trace persistence to ClickHouse for an ELK topology request.
- Interactive API routes live under `/api/v1/topology/services`, `/api/v1/topology/services/{service}/apis`, `/api/v1/topology/services/{service}/apis/{api}/principals`, service/API/principal metrics, and cursor-paginated principal IPs. They expose operational metrics, direct/inferred evidence, confidence, anonymous attribution, and previous-window change indicators.
- The frontend `/topology` route is service-only initially, expands branches explicitly, keeps source IPs in the detail panel, and preserves node positions while loading child branches.

## 29. Full-Canvas Topology Interaction Redesign (2026-09-18)

- `/topology` now uses the complete route viewport as a matte grid canvas; the previous page header, graph card, reserved inspector column, and attribution card layout were removed.
- Time-window controls, graph legend, relationship change counts, and identity-attribution quality are compact floating canvas controls.
- The detail inspector is a floating right-side window rendered only after a node or edge is clicked; closing it or clicking blank canvas restores the unobstructed graph.
- Canvas navigation supports mouse-wheel zoom, explicit `+`/`-` zoom controls (50%-250%), primary-pointer drag panning, and reset by clicking the percentage or double-clicking blank canvas.
- Service, API, and principal node cards display TPS, p95 latency, error rate, and change state as vertically stacked label/value rows for faster scanning.
- Service, API, and principal cards can be dragged independently across an effectively unbounded grid; connection lines follow the moved cards and whole-canvas panning remains unrestricted.
- The floating node inspector includes a TPS-over-time line chart backed by ClickHouse five-minute series or bounded Elasticsearch date-histogram aggregation.
- The inspector TPS chart uses a smooth curve and fixed five-minute buckets across every observation window; longer windows never change the aggregation to hourly or multi-hour buckets.
- The topology range pills were replaced by a seven-day slider containing 2,016 selectable five-minute windows. Scrubbing previews the timestamp and releasing the pointer or keyboard key commits one exact five-minute topology snapshot.
- Sidebar links leaving `/topology` use a full route load to prevent React Router's in-memory location from retaining the old canvas after the browser URL changes; modified clicks still preserve normal browser behavior.
- The topology route owns exactly the available height below the global header. Its isolated stacking context remains below the persistent sidebar, so sidebar navigation stays clickable even while the topology inspector is open.
- Added Vietnamese strings for topology canvas actions and accessible labels.
- Verification: frontend TypeScript lint and production build passed; live `/topology` and `/api/v1/topology/services?window=24h` returned HTTP 200; the Playwright suite passed **18/18** pages with zero browser exceptions and now asserts zoom/reset, hidden-until-selection inspector behavior, and `/topology` to `/services` sidebar navigation.

## 30. Canonical Service/API/User/IP Investigation Model (2026-09-19)

- `Service` remains the highest-level operational entity; no additional System entity, resolver, rollup, or anomaly layer is introduced.
- The shared topology facts support both investigation directions without inverse duplicate tables: `Service -> API -> User -> IP` and `User -> Service -> API -> IP`.
- Principal-first interactive endpoints are `GET /api/v1/topology/principals/{principal}/services` and `GET /api/v1/topology/principals/{principal}/services/{service}/apis`; source-IP evidence continues through the existing bounded, cursor-paginated principal IP endpoint with service/API filters.
- The User Access & Topology tab uses progressive disclosure. It initially renders User and Service relationships, reveals APIs after service selection, and keeps IPs outside the default topology until an API is selected.
- Existing topology tables, legacy user topology APIs, service edges, principal profiles, baselines, and anomalies remain compatible; the inverse queries reuse `topology_principal_edges_5m` and `topology_principal_ip_5m`.

## 31. Persistent Light Theme (2026-09-19)

- The frontend keeps dark mode as the default and exposes a persistent light/dark toggle in the global header.
- Theme preference is stored in browser `localStorage` under `tracescope-theme`; the root `data-theme` and browser `color-scheme` are updated at runtime.
- Light mode remaps the established matte palette globally across the app shell, shared cards, controls, tables, text, borders, scrollbars, and Recharts axes/grids without duplicating page implementations.

## 32. Operational Dashboard Refresh (2026-09-19)

- The dashboard now presents four top cards: Total TPS, Total Users, Total Services with unhealthy-service count, and Abnormal Changes.
- The main charts are Total TPS, Error %, and a horizontal stacked abnormal-score distribution. Existing dashboard series and service/user endpoints are reused without backend changes.
- Bandwidth is intentionally shown as a frontend placeholder because the existing dashboard API does not expose request/response byte series. No API or backend schema was changed.
- Global range controls were replaced by a fixed five-minute-bucket / seven-day history view. Specialized anomaly and user-topology pages no longer expose alternate time-range selectors.

## 33. Service Detail Chart Contract Fix (2026-09-19)

- `/services/:name` now normalizes the existing service detail rollup response (`bucket_start`, `requests`, `errors`, `latency_p95`) into the frontend chart contract (`timestamp_ms`, `tps`, `p95_ms`, and error-rate fields).
- The service trend chart uses numeric time axes and displays a clear no-telemetry state instead of rendering an empty Recharts surface.
- This was implemented entirely in `frontend/src/pages/Services.tsx`; no backend or API response changes were made.
- Verification: `npm run build` passed and `git diff --check` passed.

## 34. Separate Service Trend Charts (2026-09-19)

- The service detail view now renders TPS and p95 latency as separate line charts with independent Y-axis scales; the combined dual-metric area chart was removed.
- Both charts reuse the normalized frontend series from the existing service endpoint. No backend/API changes were made.
- Verification: frontend TypeScript lint and production build passed.

## 35. Card Row Layout (2026-09-19)

- Larger panel/card sections now cap at two cards per row across the dashboard, service, account, anomaly, trace, agent, principal, user, topology, and unknown-user views.
- Compact KPI/info cards (for example Total TPS, Total Users, Total Services, and Abnormal Changes) use four cards per desktop row; larger cards and charts still wrap after two.
- Data tables and topology canvases retain their functional layouts.
- This is a frontend-only responsive layout change. Verification: TypeScript lint and production build passed.

## 36. Monitoring UI Refactor (2026-09-19)

- The primary `/` route now redirects to `/dashboard`; sidebar navigation is organized as Dashboard, Services, Users, Topology, Changes, Traces, and Agent Fleet. The legacy `/unknown-users` route remains available but is no longer a primary navigation item.
- The default dashboard is organized around status and change investigation: KPI summary, important changes, five-minute TPS/error/p95 trends over seven-day history, service/user hotspots, and secondary abnormal-score distribution. The unavailable bandwidth series was not fabricated and no backend/API contract was changed.
- Services use an operational table and service detail surfaces prioritized operations. A subordinate API drilldown route (`/services/:service/apis/:api`) reuses existing topology metrics, principal, and caller APIs and keeps the Service → API → User path intact.
- User workspace headers and tabs are compacted; important changes and new relationships are surfaced before detailed charts. Topology node cards and history controls are less dense while preserving lazy expansion and the inspector.
- The grouped anomaly view now leads with eight operational columns (severity, what changed, identity, service/API, current vs baseline, since/duration, status, actions), while raw findings and expandable incident slices remain available.
- Visible terminology uses “Unattributed Traffic” / “Identity Attribution” for unknown identity observations without changing backend semantics; explicit 401/403 authentication failures remain distinct.
- Changes are frontend-only. Validation completed with `npm run lint`, `npm run build`, and `git diff --check`; unrelated backend, test, and report files remain unstaged.

## 37. Service/API/User Bandwidth Backend (2026-09-19)

### Worker metric-bucket bandwidth (2026-09-23)

- The Elasticsearch metrics stage uses its `worker_elasticsearch_sync` checkpoint to paginate bounded six-hour windows across the retained seven-day source range. It writes both 60-second and 300-second buckets and refreshes the latest ten minutes during backfill. The worker fingerprints the two most recent completed 300-second windows and marks changed ELK metric windows for anomaly detection; it also evaluates the prior day in bounded batches after first deployment. The principal-level traffic-spike detector excludes anonymous and unknown principals while retaining their traffic in service-level metrics.
- The Elasticsearch metrics stage writes grouped transaction counts, latency summaries, byte totals, and byte sample counts into worker-owned `metric_buckets` at both 60-second and 300-second grain. A byte-schema checkpoint version triggers one retained-window rebackfill after upgrading older buckets. With `OTEL_CLICKHOUSE_ONLY_AGENT_TRACES=true`, the stage skips raw Elasticsearch-to-ClickHouse sync entirely.
- `/api/v1/topology/bandwidth`, Overview, Services, API detail, and User Activity read byte totals from `metric_buckets`. Bandwidth is unavailable only when those buckets contain no measured byte samples.

- Service, API, and principal topology metrics now expose cumulative `request_bytes`, `response_bytes`, and `total_bytes`, plus explicit rates: `request_bytes_per_second`, `response_bytes_per_second`, `bandwidth_bytes_per_second`, and `bandwidth_bits_per_second`.
- Five-minute transaction series expose the same bandwidth fields for line-chart use. Both ClickHouse and Elasticsearch worker paths write and read these fields through `metric_buckets`.
- `GET /api/v1/services/{service}/bandwidth` provides a dedicated service bandwidth response with window totals and five-minute series. Existing service detail health includes the bandwidth totals/rates and a nested `bandwidth` payload.
- `GET /api/v1/users/{principal}/performance` now includes bandwidth fields per bucket, a top-level bandwidth summary, current/baseline five-minute bandwidth KPIs, and `bandwidth_pct` delta. API drilldowns receive the same fields through the existing topology API metrics response.
- Units are explicit: byte totals are bytes, `*_bytes_per_second` values are bytes/second, and `bandwidth_bits_per_second` is bits/second. Missing byte telemetry remains zero and is never inferred from request counts.
- Verification: focused interactive topology/bandwidth tests passed **5/5**; API and behavioral regressions passed **19/19**; Python compilation and `git diff --check` passed.

## Anomaly vs Behavioral Change IDs (2026-09-22)

- `anomaly_events.id` and `principal_change_events.id` are separate namespaces. Overview “What’s different” records come from `/api/v1/user-changes` and must open `/changes/chg-<id>`, not `/anomalies/{id}`.
- `GET /api/v1/user-changes/{id}` provides direct lookup, and `AnomalyDetailPage` redirects legacy mislinked change IDs to the owning User Changes tab.

## Changes Episode Experience (2026-09-22)

- Added the operator-facing `/changes` route and `/api/v1/changes` adapter above the existing `anomaly_events` and `principal_change_events` detector outputs.
- The adapter groups nearby signals by subject, incident, scope, and a bounded 15-minute window into one episode. The primary contract exposes `subject`, human-readable `summary`, `state`, `status`, `highlights`, `evidence`, `timeline`, and relationship context; detector names and scores remain secondary evidence.
- Added `/api/v1/changes/{episode_id}` with stable `chg-<id>` and `anm-<id>` source IDs. The existing detector tables and lifecycle APIs remain unchanged.
- The sidebar and dashboard “What’s different” actions now use `/changes`; `/anomalies` redirects to `/changes` while `/anomalies/:id` remains available for legacy anomaly deep links.
- Added the frontend Changes list/detail experience with operational filters for subject type, state, and search, plus Vietnamese translations for the new operator-facing copy.
- Reduced the primary User workspace to `Overview`, combined `Activity`, and `Changes`. The former `topology` and `patterns` routes redirect to combined Activity; `investigations` redirects to User Changes. The scoped TPS panel remains above all three views.
- Verification: isolated FastAPI Changes route smoke test passed, application OpenAPI registration passed, frontend `npm run lint` and `npm run build` passed, backend compilation passed, and `git diff --check` passed. Playwright 1.63.0 and Chromium were installed in `.venv`; after restarting `tracescope-30102`, the public `/changes` list and `/changes/anm-1886229056538689` detail passed Chromium checks with HTTP 200, Changes API HTTP 200, zero console errors, and zero page errors.
- `backend/requirements.txt` now includes the reproducible Playwright test dependency; install Chromium separately with `.venv/bin/python -m playwright install chromium`.

## Time-series chart stroke (2026-09-23)

- `frontend/src/index.css` defines `--chart-line-width: 1.25px` for every Recharts Line/Area curve and the custom topology-inspector TPS curve. Topology relationship edges, grid lines, and hover markers keep their separate widths. The thinner traces improve visibility of narrow peaks.

## User Activity TPS history recovery (2026-09-23)

- `/users/:principal/activity` merges performance and bandwidth-rollup buckets by the selected time resolution. The Elasticsearch rollup's measured `request_count` supplies TPS even when ClickHouse trace rows have expired or the legacy performance response rounds sparse RPS to zero. Raw performance rows still supply detailed latency and HTTP status values where available.
- For `billing_reconcile_job`, the public bandwidth API returned 1,250 measured five-minute buckets and 63,152 requests over the selected seven-day range. The rebuilt public page rendered a nonzero TPS trace with 382 line segments and displayed the latest sparse rate as `0.0033` TPS. Frontend build and Chromium page check passed with no page errors.

## User Activity metric-bucket TPS source (2026-09-23)

- The worker derives `metric_buckets` from its configured telemetry source, and `GET /api/v1/principals/{principal}/metrics?bucket=300` reads the retained five-minute rollups. User Activity uses this endpoint for transaction counts, TPS, error rate, latency, and measured bandwidth.
- Public verification for `billing_reconcile_job`: the principal metrics API returned 1,741 buckets and 119,605 requests over seven days. The rebuilt page fetched that API successfully and rendered 428 main TPS line segments with no browser page errors.

## Frontend time-series provenance (2026-09-23)

- Transaction line/area charts on Overview, Services, Service Detail, User Activity, User Changes header, API Detail, topology detail, and Unknown Users read worker `metric_buckets` for request rate, errors, and latency. User Activity baseline comes from worker baseline rollups through `/api/v1/dashboard/series`.
- API/topology detail, Overview, Services, and User Activity read transaction counts, latency, and byte rates from worker `metric_buckets` in both storage modes. Frontend charts do not query traces or a separate bandwidth index.
- Bandwidth lines use worker `metric_buckets`, and Agent Fleet lines use `agent_stats_history`.
- User Activity charts and request outcomes derive from worker `metric_buckets` and materialized `principals` metadata; the activity view does not request `/api/v1/users/{principal}/performance`. The shared User workspace header loads its identity profile from `/api/v1/users/{principal}` so an empty selected-window series cannot make an existing principal appear missing. The outcome bar reports non-error versus failed requests because metric buckets do not retain exact HTTP status classes.
- User Activity Access reads worker `topology_principal_ip_5m` rollups. If an Elasticsearch deployment has not materialized IP relationships in ClickHouse, Access has no relationship rows; it does not query raw APM for them. Unknown Users' trend uses `metric_buckets`; its other summary/evidence sections still use trace data.
- The workspace keeps historical activity visible from retained five-minute buckets when the one-minute profile view is empty. It does not invent a principal when both are empty.
- In `OTEL_CLICKHOUSE_ONLY_AGENT_TRACES=true` mode, the Elasticsearch worker now queries transaction aggregates server-side and writes only grouped 60s/300s `metric_buckets` into ClickHouse. It refreshes the latest ten minutes and backfills the Elasticsearch seven-day retention window through a bounded checkpoint. No application trace document is copied into ClickHouse by this stage. Elasticsearch latency percentiles in this path use Elasticsearch's percentile aggregation and are approximate.

## Raw-trace read boundary and topology navigation (2026-09-24)

- User-facing analytics and topology APIs must read worker-owned `metric_buckets`, topology rollups, and other aggregate/read-model tables. Keep raw ClickHouse `traces` access in ingestion and explicit worker/backfill processing only; do not add a request-time fallback to raw spans.
- When analytics use ClickHouse while raw traces use Elasticsearch/ELK, interactive topology must read the worker's ClickHouse `metric_buckets`; the legacy topology edge tables may be empty in this split-storage mode. A transaction with no caller service still contributes its target service/API, but must not create a fabricated caller node or edge.
- Prometheus `/metrics` reads the worker snapshot/checkpoint; if neither exists yet, return an empty snapshot instead of running worker aggregation in the API process.
- Trace Explorer remains a separately documented temporary exception: it reads the store selected by `OTEL_TRACE_STORAGE_BACKEND` (Elasticsearch for live APM, ClickHouse `traces` for an offline testbed). Keep raw table reads isolated to its two repository methods and ingestion deduplication; do not add this access to other APIs.
- Interactive topology renders service nodes and service-to-service edges only. API, principal, and IP detail stays in lazy, bounded DOM panels; navigation supports Service → API → User and User → Service → API. Use the stable `service_edge_id` helper and backend `edge_ids` for yellow path highlighting.
- Selecting a service highlights its connected service edges in yellow; selected API/user paths use their backend edge IDs. Highlighted edges render above context edges with yellow arrowheads. Click outside a relationship panel or use its close button to dismiss the scrollable panels; the User directory can be reopened from its Users button.
- API and User selections fetch scoped service connections from the five-minute topology rollups. The yellow line and TPS label reflect the selected API/User plus any chosen Service/API scope; unrelated service edges stay blue. The User-focused endpoint is `GET /api/v1/topology/principals/{principal}/connections` with optional `service` and `api` filters.
- The `/topology` canvas keeps its floating title/search/mode card compact, caps relationship lists at 240px wide and 220px high, places history in a small on-demand popup, and uses compact zoom and legend controls to leave more graph visible.
- Preserve graph coordinates on selection, panel changes, and metric refresh. Read-model rollups and interactive lists must use bounded windows and keyset pagination where cardinality can be high.
- Database connection role is selected with `OTEL_CLICKHOUSE_ROLE=api|worker|owner`; role credentials fall back to the existing base credentials when unset. The API role needs rollup reads; it needs raw `traces` SELECT only while the temporary ClickHouse-mode Trace Explorer is enabled. ELK mode does not require that grant.
- See `docs/topology-read-model.md` for the table boundary, topology flow, edge ID rule, and role grant guidance. The AST boundary regression lives in `tests/test_api_read_model_boundary.py`.

## Active ELK worker and Trace Explorer repair (2026-09-24)

- The Sep 23 bandwidth-rollup change introduced `topology.metric_operation` with Painless `replaceAll` calls using string regex arguments. Elasticsearch 7.17 rejects them with `Cannot cast from [java.lang.String] to [java.util.regex.Pattern]`, causing the worker's `process_elasticsearch` stage to fail with HTTP 400 while APM ingestion continues.
- `backend/app/repositories/elasticsearch_metric_repository.py` now uses Painless regex literals and replacement lambdas. The live aggregation request returns HTTP 200; the restarted worker completed the ELK stage and wrote recent 60-second and 300-second metric buckets. The seven-day checkpoint backfill continues on its normal 60-second cadence.
- `run_server.sh` keeps the analytics/topology backend on ClickHouse and selects Elasticsearch for Trace Explorer via `OTEL_TRACE_STORAGE_BACKEND`. This avoids a ClickHouse SQL error in the broad ELK topology path while resolving live APM trace `2fed16bb627eb937602ba972d48c456c` through both list and waterfall APIs on `:30102`; before the change the same ID returned an empty list and 404.
- The older cluster worker at `10.244.1.196` still writes DNS failures to the shared `jobs` row. The active host worker's Elasticsearch requests and cycles succeed; `/api/v1/ingestion/status.jobs` may show either worker's latest write until the older deployment is updated separately.


## Service operations redesign (2026-09-28)

- `/services`: compact observed-service/open-anomaly/request/error summary, TPS chart, searchable sortable fleet triage with anomaly/error filters, 10-row pagination, metadata context and API/User counts. Loaded coverage is capped at 500; no-open-anomaly is not labeled Healthy or treated as an availability/SLO measurement.
- `/services/:name`: TPS and metric overlays first, recent changes beside expandable caller/dependency evidence, then selectable API/User/Instance/Trace sections. API inventory has search and 15-row pages; latency is explicitly maximum bucket percentiles. Removed estimated HTTP status counts and fixed slow-rate columns in favor of measured error rate and traffic share. Instance average latency maps the actual response field; missing bandwidth displays a dash.
- Change, Trace and dependency links preserve time context. Catalog environment/group/module/service filters apply to loaded rows; operation/account filters affect the estate chart, with that difference disclosed when selected. Backend APIs and retention unchanged; frontend bundle served on port 30102 without restarting backend or worker.
- Validation: production TypeScript/Vite build and diff check passed. Chromium verified live catalog/detail APIs (all HTTP 200), search/sort, API and fleet pagination, all four detail views, and 1440px/390px/844px layouts without page overflow or JavaScript errors. A mocked 240-service fleet, empty catalog and HTTP 503 state passed. Screenshots: `/tmp/services-redesign-desktop.png`, `/tmp/service-detail-redesign-desktop.png` and corresponding mobile files. Browser smoke script: `/tmp/check_service_redesign.py`.


## Selected Service access board (2026-09-30)

- Redesigned the Access board on `/services/:name` to be unblocked and multi-directional: all three columns (Observed credential, Observed IP, API) are populated and selectable immediately on load without forcing a sequential 1 → 2 → 3 dependency.
- Backend API `GET /api/v1/topology/services/{service}/ips` returns all `(principal, source_ip, api, caller_service)` combinations for the service using `GROUP BY source_ip, service, api, caller_service, principal` and bounded cursor pagination. Fixed ClickHouse ILLEGAL_AGGREGATION in `HAVING` clause by referencing aliased columns directly.
- Frontend `ServiceAccessBoard`:
  - Queries `/api/v1/topology/services/${service}/ips` on mount (`enabled: !!service`).
  - Supports clicking any column first: Credential, IP, or API. Selecting an item cross-filters the other columns to only show related items while highlighting the active selection.
  - Clicking an active selection toggles it off. A "Reset filters" button clears all active selections.
  - Drilldown summary at bottom displays active filter tags with clear buttons, measured requests/TPS/error rate/max P95, caller services, and Trace link scoped to the selected combination.
- Added Elasticsearch composite IP aggregation fallback `_es_principal_ips`: when `topology_principal_ip_5m` in ClickHouse has no pre-aggregated rows for a service/principal (e.g. under `clickhouse_only_agent_traces: True`), it queries Elasticsearch directly using runtime mappings (`topology.source_ip`, `topology.principal` supporting WSSE usernames `wsse_username`/`wsse_user`/`user_name`), extracts client IPs (including `x_real_ip`, `x_forwarded_for`, and `client.ip`), and caches the resulting rollups into `topology_principal_ip_5m`.
- Validation: Pytest unit tests in `tests/test_interactive_service_topology.py` (8/8 passed); live tests verified `frank_wsse` -> IP `125.235.20.19`, `alice_wsse` -> IP `14.225.210.15`, etc.; frontend TypeScript build (`tsc -b && vite build`) passed with 0 errors. Backend and UI bundle served on port 30102.


## Change metric comparison clarification (2026-09-28)

- Investigated live navidrome episode `anm-4667094840709039`: saved detector baseline 0.41 TPS versus 4.71 TPS from 1,414 requests in the five-minute bucket starting `1790582400000`. Dashboard one-minute bucket request counts for that interval sum to exactly 1,414. The surrounding one-hour means are 0.907833 and 1.399833 TPS; they use different windows. Stored percentage uses the unrounded learned baseline, while displayed baseline is rounded.
- Change detail now labels hourly bucket averages explicitly, labels saved comparison as Detector reference / Observed value instead of Before / Now, and explains five-minute service traffic detection and latest values in coalesced records. Chart reference is identified as current baseline/fallback, distinct from the baseline saved at detection. Hourly averages explicitly exclude the end boundary. English and Vietnamese copy updated.
- Validation: live changes/anomaly/series reads succeeded; exact request-count reconciliation passed; TypeScript/Vite production build and diff check passed. Chromium checked live values/labels and 1440px/390px layouts with no page errors or document overflow. Browser check: `/tmp/check_change_metrics.py`; screenshots `/tmp/change-metrics-1440.png` and `/tmp/change-metrics-390.png`. Frontend rebuilt for port 30102; backend/worker not restarted.

- Follow-up consistency fix: the Change in context headline now repeats the saved detector reference/observed values shown in The changed pattern. The plotted line remains one-minute context; its caption states that Service traffic detection uses five-minute windows. This removes conflicting hourly averages from the headline while keeping surrounding trend context.
- Validation: production frontend build passed; existing live data reconciliation established 0.41 TPS / 4.71 TPS. Backend and worker were not restarted.


## Change episode grouping and latest metric fix (2026-09-28)

- Service change detail could present a current traffic drop in the chart summary while the main metric panel retained an older, larger spike. The panel chose the largest percentage delta; it now preserves the latest signal's same metric, matching the chart summary.
- Episode keys now include the 15-minute time bucket even when a source incident ID is present, preventing a long-lived ID from joining changes from separate periods. Context chart centers on the latest signal, while the episode's original start/last-seen range remains available in the timeline and duration.
- Validation: backend module compiles; production frontend build and diff check passed. Active API unavailable in this environment, so no live endpoint or browser verification was possible. Backend/worker were not restarted.


## Detailed alert messages (2026-09-28)

- New alert outbox payloads retain public episode highlights, evidence, signals/count and policy assessment. Scope resolves Service/API/caller/IP from episode context and observed credential from User subject.
- Telegram messages include rule severity, evaluation/workflow, summary, scope, UTC timestamps, detector reference/observed metrics with units/delta, evidence and assessment, plus Change ID/link. Plain text supports legacy payloads and is capped at 4,000 UTF-16 units with space reserved for the link. Webhooks receive the enriched JSON; raw trace/auth records are not added.
- Validation: four isolated unittest checks passed (format/zero values, legacy fields, Unicode length/link preservation, mocked enqueue and Telegram delivery). Live health and alert-deliveries GET endpoints returned HTTP 200 on port 30102. No external test notification was sent.
- Backend/worker NOT restarted: activation remains pending alongside the existing policy-v2 rollout review. Existing queued payloads can only show their originally stored details.


## Inventory-first Services catalog (2026-09-28)

- `/services` now presents a compact inventory summary (observed Services, APIs, environments, groups) followed directly by the service directory. Removed the estate TPS chart, its dashboard-series request, and the catalog TPS column/sort labels. Service detail retains its scoped TPS and metric overlays.
- Directory adds an environment selector, metadata-aware search hint and empty-result filter reset. Signal tabs, request/error/latency sorting, 10-row pagination, canonical entity links and loaded-500 coverage remain. Catalog priority ties use request counts. Account/operation filter copy now correctly explains that these do not narrow the inventory.
- This supersedes the earlier catalog TPS requirement; detail/API/User workspace TPS requirements remain in force.
- Validation: production TypeScript/Vite build and diff check passed; live Services API returned HTTP 200. Chromium verified live catalog/detail navigation and retained detail TPS, absence of catalog dashboard-series requests, mocked 240-Service filtering/sort/pagination/reset, empty/error states, and 1440px/390px/844px layouts without document overflow or page errors. Screenshots: `/tmp/services-catalog-desktop.png`, `/tmp/services-catalog-390.png`; smoke script `/tmp/check_services_catalog.py`.
- Frontend bundle rebuilt and served on port 30102; no backend changes or restart required for this revision.


## Jev advisory integration (2026-09-29; not activated)

- Extended the existing semantic layer with typed OpenRouter Decisions recommendations using `typesafe/jev-1.13`, persisted confidence/distributions and submitted signal IDs. Jev remains advisory: deterministic state/severity and operator/alert actions are unchanged.
- Added the opt-in analytics-worker stage, bounded input/batch/time budgets, critical-first processing, successful-result caching, failed/abandoned-pending retry cooldowns, and evidence-sensitive episode versions. Global and User Change detail share the localized advisory UI, including stale results and submitted evidence.
- Added migration `015_semantic_adviser.sql`, non-secret Helm ConfigMap settings and Secret-only API-key wiring. Enabled Helm configurations require one app/worker owner. Existing ignored secret values were not read or changed. Defaults remain disabled.
- Verification: 95 isolated focused/related tests passed with mocked provider calls; Python compilation, TypeScript/Vite build, Helm lint/template and diff checks passed. Chromium verified EN/VI, successful/stale/pending/failed/unevaluated output, evidence disclosure, and 1440px/390px/844px layouts without overflow or page errors. Existing Vite chunk-size and Starlette/httpx warnings remain.
- Build output is `/tmp/jev-frontend-build`; served `frontend/dist` was not replaced. No production migration, restart, deployment, real LLM request, commit, push, or Kubernetes command. Unrelated tracked dirty diffs were compared with the initial snapshot and preserved.
- Configuration, lifecycle, API fields, limits and verification details: `docs/jev-adviser.md`.


## Jev standalone activation (2026-09-29)

- Reviewed the implemented Jev advisory layer and started the local dashboard and single analytics worker with `./run_server.sh start`; dashboard listens on `0.0.0.0:30102`, bootstrap remains on `30105`, and Elasticsearch NodePort `32073` is reachable.
- Live Jev assessments were explicitly authorized. The existing root `.env` already enabled the semantic layer and configured its API key; no secret or configuration change was needed. Jev remains advisory and uses `typesafe/jev-1.13` through OpenRouter Decisions.
- Fixed migration 015's comment semicolon, which the existing statement splitter would interpret as SQL. Added a regression test exercising the actual migration runner with a mocked client. Verified migration 015 is installed with all four new columns; the migration runner and repeat run both reported no pending migrations at verification time.
- Rebuilt the current frontend into served `frontend/dist`. Validation: 96 isolated Jev/policy/API/investigation/deployment tests passed, POSIX shell syntax and diff checks passed, and production frontend build passed (existing large-bundle warning). Tests exclude root conftest's broad test-database cleanup.
- Confirmed live OpenRouter HTTP 200 responses and a completed worker cycle with 39 eligible episodes, 2 assessed, 0 failed. Changes list and detail returned persisted successful recommendations and submitted signal IDs. HTTP 200 checks passed for `/`, health, Changes list/filter/detail, Services, and ingestion status; an unknown Change returned 404.
- Runtime health reports `demo_mode=true`, analytics on ClickHouse, and Trace Explorer on Elasticsearch. Starting the current working tree also activates its other existing backend/frontend changes. No Helm deployment or Kubernetes commands were used.


## Changes Jev result placement (2026-09-29)

- `/changes/:id` now places the shared **Jev AI result** card beside the change-in-context chart for both Service and User episodes, replacing Change scope and Access pattern. Removed the duplicate lower assessment and the unused before/after access queries.
- Retains recommendation, probability/confidence, submitted evidence, and stale/pending/failed/unevaluated states in English and Vietnamese. The shared User workspace assessment uses the same Jev title.
- Rebuilt served `frontend/dist`; HTTP checks confirmed healthy API and the current bundle on port 30102. Chromium validated both subject types, both languages, all five assessment states, and 1440/390/844px layouts without overflow or page errors. Build and diff checks passed; no backend restart or migration required.


## Online behavior learning and learned topology (2026-09-29)

- Added a separate `/behavior` workspace (Overview, Learning graph, Profiles, Deviations, Contracts), source-scoped persistent memory, TPS learning, scoped immutable operator decisions, and bounded stored Jev advisories. Python/FastAPI/ClickHouse worker plus existing React/TypeScript/Recharts/SVG; no added ML library or graph database.
- Every completed five-minute observation reinforces typed nodes/edges once. Seven-day support half-life, exponentially weighted TPS mean/variance, score-before-update, withheld material spikes, deterministic late-data replay, durable snapshot publication, and bounded cleanup. Engine version `online-behavior-graph-v3` includes learned service-call edges as well as API ownership and credential/IP associations. Repetition never grants access approval; no packet enforcement.
- `/topology` now reads `/api/v1/behavior/topology` and its detail endpoint exclusively. Replaced the seven-day/selected-window merge and slider with source/environment selectors and learned state. Preserved service-card dragging, zoom/reset/re-layout, expandable API/credential lists, reverse credential navigation, search, exact-path highlighting, entity links, and the floating inspector. Added keyboard edge selection. Old topology API endpoints remain for other consumers.
- Inspector shows observed/expected TPS, freshness, a plain-language behavior state, a compact recent chart, and related IP evidence. Internal model counters are hidden from the operator view. Missing latency/error/health/IP-volume facts are not fabricated. Source/environment namespaces remain separate; missing callers produce no call edges. Global time filters do not truncate learned memory. The topology projects up to 500 services and 2,000 learned service edges, disclosing caps.
- Additive migrations 016 and 017 verified installed. Local dashboard and single worker restarted using `./run_server.sh restart`, active on `0.0.0.0:30102`; ES NodePort `32073` reachable. Standalone learning enabled; Helm remains disabled by default and enforces a single app replica when enabled. Local ownership locks are not distributed; only one learning/review owner may run against these tables.
- Validation: 135 isolated backend/storage/graph/topology/policy/API tests passed without root conftest or production-data test mutations; frontend production build, Helm lint and POSIX script/diff checks passed. Chromium exercised Behavior and learned Topology in EN/VI at 1440/390/844px, including drag/zoom, drilldowns, exact-path highlights, reverse navigation, source/environment switching and empty states. Live topology/detail APIs return learned data. Production bundle retains the existing size warning.
- Full behavior observations retain 30 days; compact daily memory 90 days; old graph/profile snapshots seven days, with hourly obsolete-generation cleanup. Existing ES seven-day and ClickHouse raw one-day policies unchanged. See `docs/learned-behavior.md` for source caveats, replay, access rules, capacity and recovery. No Helm rollout, Kubernetes command, commit or push performed for this revision.


## Topology spider layout (2026-09-29)

- Initial placement and Re-layout now use a deterministic, bounded force layout: learned connections attract related services, hubs settle among their neighbors, and rectangle collision checks preserve card clearance. Residual overlap resolves via local spiral placement rather than grid rows.
- Removed the square background grid and changed link routing to straight connections. Manual dragging, selection, zoom/reset and drilldowns are preserved. Layout works in measured CSS pixels before conversion to canvas coordinates.
- Geometry verification covers 1/16/200/500 services for repeatable placement and non-overlap. Production build and EN/VI Chromium checks passed at 1440/390/844px, including dragging, edge keyboard selection, drilldowns and source switching. Live page rendered 16 service cards without page errors; served bundle `index-Nt5fMzHr.js`.


## Straight topology edges and anonymous service coverage (2026-09-29)

- Topology connections now use straight SVG line segments; scattered spider placement and interactions remain.
- Navidrome was missing because all its metric traffic was anonymous: audit found 188,939 requests across 2,728 five-minute buckets, with no caller attribution. Fixed worker summaries to retain anonymous traffic for Service/API graph learning while `build_profiles` continues to exclude it from credential profiles, approvals and user findings. No anonymous credential node or invented caller edge is created.
- Online graph algorithm version is now `online-behavior-graph-v3`. Replayed retained metric history and restarted the local dashboard/worker; no new schema migration. Regression suite: 136 isolated tests passed, including anonymous service visibility and identity isolation.


## Operational topology UI (2026-09-29)

- Removed retained request totals, observed/reference/withheld window counters, previous-reference TPS and first-seen timestamps from the topology inspector; cards and relationship lists no longer show cumulative training counts. Internal model state remains available to the worker/API.
- Inspector now focuses on observed TPS, expected TPS when ready, a compact trend, relative observation freshness and plain-language behavior state. States distinguish learning, learned pattern, elevated TPS and no recent observations; they do not assert service health. IP evidence stays available without window counters.
- Relationship drilldowns use indexed entity lookup and grouped edge IDs instead of repeated full-list scans. Search ranks exact matches and Services ahead of API-name matches. UI still reads bounded source/environment snapshots, pages lists by 100, and refreshes once per minute rather than rendering individual traces. No million-trace/day throughput certification is implied by the UI work.
- Reviewed Changes: it currently consumes existing anomaly/user signals and their detector baselines, not the new online graph. Recommended integration is versioned, source/environment-scoped learned baseline evidence and correlated deviation candidates, retaining persistence/quality/material-impact gates and duplicate suppression. No Changes severity or alert-routing change made by this UI revision.
- Frontend rebuilt to `index-BULjlgSd.js`; no backend restart or migration required. Final browser checks cover removed counters, EN/VI and existing topology interactions.

## Consistent Changes naming (2026-09-29)

- Global and User Changes share localized detector labels across titles, filters, evidence and timelines. Titles include the subject and every distinct signal type in stable order, rather than selecting the first detector. Covers service, behavioral/authentication, identity/IP, telemetry quality and learned graph signals; unknown types retain a readable fallback.
- UI uses Observed changes, Baseline, Observed, Detected signals, Assessment, Next step, Assessed by, Priority and Review status. Jev priority display maps investigate to Needs attention and urgent to Critical; stored provider values and deterministic flagging behavior remain unchanged. Expected remains an explicit operator disposition.
- Validation: production frontend build and diff check passed; isolated TypeScript naming checks covered 35 detector identifiers in EN/VI, grouped-title deduplication and ordering, authentication naming and empty fallback. Live Changes API returned HTTP 200 through the approved host access. Frontend dist rebuilt; no backend restart.

## Learned access flow, matrix and shared encoding (2026-09-30; backend not restarted)

- New bounded endpoint `GET /api/v1/behavior/access` (`view=flow|matrix`) in `backend/app/api/behavior.py`, projection in `backend/app/services/behavior_access.py`. It reads only the persisted learned-graph snapshot plus the profile/deviation read models; no raw `traces`/Elasticsearch (`tests/test_api_read_model_boundary.py` passes). One endpoint serves both views.
- Flow: chain Caller Service → observed credential → Service → API → peer IP with one focus (`focus_type`/`focus`) and cross-filters (`service`, `api`, `credential`, `caller`, `ip`). Top N per column (default 12, max 50) plus one "Other (k)" bucket; `basis=observed|baseline`; `window_minutes` (5–1440) defines "current" relative to the learned-through time, so a lagging worker does not turn everything into ghosts. IP column is role groups by default (`ip_role`, `ip_offset`, `ip_limit` expand one role into paged IPs); LB/proxy/NAT/infrastructure are flagged and never the origin; IP ribbons have fixed width because per-IP volume is unknown. Missing caller/credential adds no ribbon; anonymous traffic keeps Service/API flows and is never a credential node or matrix row.
- States: `established`/`emerging`/`dormant` (profiles, else graph fallback), `new` (first seen inside the window or unreviewed access_expansion), `deviating` (surge streak ≥3, material surge in window, or open traffic_surge/contract_violation/graph_tps_shift), `ghost` (learned, not observed in window). Merged ribbons/nodes show the worst constituent.
- Matrix: credentials × APIs, rows ordered by greedy Jaccard similarity (busiest 1,000 only, disclosed), columns by barycenter of ordered rows; pages ≤200×200 (UI 25/50/100) with "showing X of Y".
- Frontend: `accessEncoding.ts` (states: solid / dashed / dotted ghost / orange with distinct dash + glyph `+`/`!`), `accessLayout.ts` (plain-SVG Sankey, no new dependency), `AccessFlow.tsx`, `AccessMatrix.tsx`, `BehaviorAccess.tsx` (new `/behavior?tab=flow` and `?tab=matrix`). `ServiceAccessBoard` now leads with the Sankey and shares one selection with the old observed lists (kept in a collapsed section). Topology edges use the same encoding (TPS width, observed/baseline toggle, legend, markers) and the inspector has "Open access flow", which opens the focused Sankey in a drawer. Copy is EN/VI inline via `t(en, vi)` as in neighbouring components.
- Ribbon sparkline uses `/behavior/topology/detail` for the most specific graph object of the ribbon (API, credential or service-call edge); caller→service ribbons have no exact series.
- Validation: `tests/test_behavior_access.py` 10/10 (states, top-N/Other, no-caller, anonymous, IP roles, endpoint, 320 credentials × 200 APIs synthetic graph: flow + matrix ≈1 s); boundary test and graph/learn-window tests pass; the only failure is the pre-existing `test_behavior_topology.py::test_service_edge_reinforces_once_with_multiple_apis` (`topology_series` `expected_tps`). `npm run lint`, production build (into `/tmp/access-flow-build`) and `git diff --check` pass. Chromium 123/123 checks at 1440/844/390 px in EN and VI (no page errors or document overflow; all five states, cross-filter/reset, Other bucket, IP expand/paging, sparkline, matrix sort/paging/keyboard, topology drawer); matrix 2,500 cells rendered in well under 1 s. Screenshots: `/tmp/access-flow-*.png`, `/tmp/access-matrix-*.png`, `/tmp/access-topology-*.png`. Browser runs used a mock server with synthetic graphs and the real projection code; real learned graph (72 relations) was also projected read-only without errors.
- Pending activation: `frontend/dist` was NOT rebuilt (new UI calls `/api/v1/behavior/access`, which needs a backend restart). `./run_server.sh restart` then `npm run build` activates this together with the other pending changes. No migration, commit or push.

## Access card restyle (2026-09-30; frontend only, served)

- `/services/:name` Access card, `/behavior?tab=flow` and the topology drawer share the restyled `AccessFlow`. Changes: thin node bars with labels beside them (no empty boxes), full-width responsive columns (`accessLayout.ts`, ResizeObserver; scrolls inside the card below 190 px per column), ribbon edges stroked only along the flow (established has no stroke; learning dashed; new/deviating orange with a glyph only on ribbons ≥5 px; ghost dotted), API labels drop the redundant Service prefix, one toolbar of segmented controls, clickable legend chips that emphasise one state, an inspector that defaults to the focus entity, and a table view. Colours in SVG use `--theme-*` variables so light theme works. Card chrome lost the duplicate counts, panel reset and idle hint.
- New components use explicit EN/VI pairs; the shared dictionary had overridden generic keys (for example "New" → "NEW", "Established" → a baseline label).
- Validation: lint, build and `git diff --check` pass. Chromium 123/123 checks passed again (1440/844/390, EN/VI). Screenshots: `/tmp/access-card-*.png`. `frontend/dist` rebuilt; no backend restart.

## Access flow hover fix and dense layout (2026-10-01; frontend only, served)

- Hover glitch causes (`frontend/src/components/AccessFlow.tsx`): each node's invisible hit rect covered the whole column gap over the ribbons, thin ribbons had a 12px invisible stroke covering neighbours, per-element mouseenter/leave caused a transient null (fade flash), a stale hovered/focused id after a refetch faded every ribbon, and the inspector changed height on hover.
- Fix: one delegated `pointerover` handler on the SVG (`data-hid`), node hit area sized to the bar plus the drawn text, a 7px pointer band only for ribbons thinner than 7px, the hover/selected highlight drawn in a pointer-transparent top layer (no reordering), hover ids checked against the current layout, keyboard focus drives hover only when `:focus-visible`, a fixed-height inspector (truncated title, reserved link row), and the selected ribbon keeps its endpoint names after a filtered refetch.
- Dense layout (`frontend/src/accessLayout.ts`): 4 barycenter crossing-reduction sweeps (Other/IP groups pinned last); at >=16 nodes in a column compact mode (17px rows, one label line, TPS in tooltip and inspector); chart body scrolls at 560px under sticky column titles; toolbar "Find credential, API…" box dims non-matching nodes and ribbons.
- Validation: lint, build and diff check pass. In Chromium (live order-service + synthetic 50 credentials x 50 APIs, 1440/844px): no page errors, no frame where every ribbon is faded during a 60-step pointer sweep, constant inspector height, no document overflow. `frontend/dist` rebuilt; no backend change.
- Follow-up (same day): ribbons are now non-interactive (`pointer-events: none`, no hover, no focus). Only items (Caller Service/credential/Service/API/IP) react: hover shows a fixed-format info box under the item (kind, state, observed/expected TPS, last seen; replaces the native `<title>`) and never fades or changes the inspector; click selects the item locally (its direct ribbons highlighted, others faded, no refetch) and the inspector shows it, with a "Filter flow to this" action for the old filter behaviour. Ribbon selection for the TPS-vs-expected chart is in the table view. Verified in Chromium (live + 50x50 synthetic): 0 reactions over empty space or ribbons, info box on 8/8 items, no fade on hover, constant inspector height, 0 refetches on click.
- Follow-up 2 (same day): the item info box is portalled to `document.body` with `position: fixed`, floats 10px to the LEFT of the hovered bar and is vertically centred on it (clamped to the viewport); when the viewport has no room on the left (the Caller column next to the sidebar rail) it flips to the right of the label. Any scroll or resize hides it. A document `pointerdown` outside an item clears the clicked item / table-selected ribbon, except inside the inspector and table view (`data-keep-selection`), so "Filter flow to this" still works. Verified in Chromium: box left of the bar for credential/service/API (gap 10px, centre offset ≤1px), flips right for caller, hidden after scroll; selection kept on inspector click, cleared on empty-chart and header clicks; no page errors.
- Follow-up 3 (same day; backend + frontend; local dashboard `:31102` restarted via `./run_server.sh restart`, host worker stays disabled): `project_flow(..., collapse_service=None)` drops the Service column when `focus_type == 'service'` (the single Service bar merged every ribbon and hid which credential reaches which API). Columns become Caller -> Credential -> API -> IP and ribbons run Credential -> API from the full relationship records, so they are exact; traffic without a credential still sizes API bars but adds no ribbon. Other focus types are unchanged. Detail ids for Credential -> API ribbons use the credential node. Frontend: minimum ribbon 4px and measured bar 10px, a fuller TPS scale (300-560px band, 720px compact), "Caller links: Simplified | All" (auto-simplified above 12 Caller -> credential ribbons: grey, no outline, the clicked item's ribbons still drawn in full), softened outlines in bands of more than 24 ribbons, and an inspector hint when nothing is selected. Tests: `tests/test_behavior_access.py` updated plus a new exact credential->API test, 17/17 with the boundary test; `test_behavior_topology.py::test_service_edge_reinforces_once_with_multiple_apis` is the known pre-existing failure. Live: order-service returns 65 credential->API ribbons; Chromium live + 12 callers x 50 users x 40 APIs synthetic: no page errors.
- Follow-up 4 (same day, frontend only): replaced the caller-only toggle and outline softening with one "Links: Simplified | All" control. In auto mode any band (Caller -> credential, credential -> API, API -> IP) with more than 12 ribbons is simplified: grey fill (fainter for ghost/dormant), no outline, except new/deviating ribbons, which keep their orange encoding; a clicked item's ribbons are redrawn in full above the band. Live order-service: 90/90 ribbons simplified with 0 outlines by default, "All" restores 90 outlined, no page errors.

## Access explorer redesign for large Services (2026-10-01; backend + frontend, local `:31102` restarted, not committed)

- The Sankey did not scale past ~15 items per column. The "Access for {service}" card (`ServiceAccessBoard`) now uses `frontend/src/components/AccessExplorer.tsx`: (1) **Unusual now**, a ranked exception list; (2) three linked, searchable, server-paged lists **Caller Service | User/credential | API** (any column first, clicking filters the other two and keeps the clicked column's siblings, unusual rows pinned with an orange edge); (3) a **selection panel** for one entity: direct neighbours on each side joined by angled (elbow) SVG connectors sized by TPS and styled by state, max 12 per side + "N more", TPS-vs-expected series, peer IP evidence, entity link. The old collapsed observed lists were removed from the card; the observed metrics summary (requests/error/P95/callers/Traces link) is kept. The full Sankey remains on `/behavior?tab=flow` and in topology.
- Backend: `GET /api/v1/behavior/access?view=lists&service=...` -> `project_lists()` in `behavior_access.py` (params `caller|credential|api` filters, `q_<column>` search, `<column>_offset`, `limit` <=200, `sort=tps|name`, `select_type`+`select`). Snapshot-only (no raw traces). Unusual reasons: `fanout` (a credential reaching >=3 new APIs in the window, one item instead of one per API, bot-like), `surge`/`flag` (deviating state, TPS x expected or learning flags), `new`, `silent` (established path that stopped within the last 24 h; older silences and still-learning paths are excluded to avoid flooding). `relation_facts` now carries `flags`.
- Tests: new `tests/test_behavior_access_lists.py` (faceting, fan-out folding/ranking, new/silent rules, search/paging/selection, 900 credentials x 220 APIs (66k relations) ~2 s, endpoint); with `test_behavior_access.py` and the boundary test 23/23.
- Browser (Chromium, VI): live order-service (3/13/8, 0 unusual, selection shows 2 callers + 8 APIs) and a synthetic 600 x 150 + injected bot/surge/new/silent graph through the real projection (~1 s per request): bot ranked first and filters the API list to its 37 APIs, "show more" loads 200, search works, 1440/390 px without overflow or page errors.
- Follow-up (same day): every selection is one centre with two labelled direct fans: Caller -> (users it sends | APIs it reaches), User -> (sent by | APIs it reaches), API -> (called by | users used). Pairs come from the full relationship records, so Caller<->API is exact. Silent lines are drawn under solid ones and each side's join into the centre box is drawn once. Tests 17/17 (`test_behavior_access_lists.py` + `test_behavior_access.py`); live check: `traffic-ui` 12 users / 6 APIs, `/api/v1/orders/process` 1 caller / 9 users, no page errors.
