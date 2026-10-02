# TraceScope Frontend UI Context

> Inventory and working context for the complete frontend implementation.
>
> Scope: `frontend/` source and build configuration. Generated dependencies (`frontend/node_modules/`) and compiled output (`frontend/dist/`) are intentionally excluded from the source inventory because they are build artifacts.

## 1. Frontend at a glance

- **Framework:** React 19 + TypeScript 5.8.
- **Build:** Vite 7, PostCSS, Tailwind CSS 3.
- **Routing:** `react-router-dom` v7 through a single route tree in `src/App.tsx`.
- **Server state:** TanStack React Query. Default query policy is 15 seconds stale time, one retry, and no refetch on window focus.
- **Charts:** Recharts for most operational charts; ECharts is used by selected large/interactive visualizations.
- **Icons:** `lucide-react`.
- **API client:** `src/api.ts`; relative `/api` requests in production, optional `VITE_API_URL` and `VITE_API_KEY`.
- **Localization:** `src/i18n.tsx`; Vietnamese is the primary visible language in many operator-facing strings, with English fallbacks and a persistent language switcher.
- **Theme:** Dark default, persistent light/dark mode via `localStorage` key `tracescope-theme`.
- **Primary shell:** Fixed compact left rail plus sticky global toolbar. Desktop rail starts at 58px; mobile hides the rail.
- **Current product model:** Dashboard, Services, Users, Topology, Learned behavior, Changes, Alerts, Traces, and Agent Fleet. Legacy routes redirect to the current operator surfaces.
- **Canonical investigation path:** `Service -> API -> User/credential -> IP evidence`, with relationship/access views progressively disclosing detail.
- **Throughput terminology:** UI uses TPS. Existing API compatibility fields may still expose RPS aliases.

## 2. Runtime composition

`src/main.tsx` mounts the following providers in order:

1. `React.StrictMode`
2. `QueryClientProvider`
3. `I18nProvider`
4. `BrowserRouter`
5. `App`

`src/App.tsx` supplies the application shell and two app-wide contexts:

- **FilterContext:** URL-backed global filters: `start`, `end`, `timezone`, `environment`, `group`, `module`, `service`, `operation`, `account`, `caller`, and `comparison`.
- **ThemeContext:** `dark` / `light` state and toggle.

Global navigation and controls:

- `SideNav`: grouped navigation with Dashboard, Explore, Changes, Investigate, and System sections.
- `FilterBar`: current entity breadcrumb, global search, fixed current-5-minute / seven-day-history indicator, refresh, filter drawer, language switcher, theme switcher, timezone selector, and Live indicator.
- Global search recognizes IP addresses, `service:`, `user:`, `change:`, `trace:`, trace IDs, `service/API` patterns, exact services, and exact APIs.
- Filter changes are written to URL search parameters; changing Service clears Operation.

## 3. Route map and user-facing surfaces

### Dashboard

- `/`, `/overview` -> redirect/alias to `/dashboard`.
- `/dashboard` -> `OverviewPage`.
- Fleet-level operational summary, current TPS, user/service counts, abnormal changes, current health context, important changes, service/user hotspots, time series, error distribution, and supporting charts.

### Services and APIs

- `/services` -> `ServicesPage`.
  - Inventory-first service directory.
  - Search, environment filtering, anomaly/error/latency/request sorting, pagination, observed service/API/environment/group summaries.
- `/services/:name` -> `ServiceDetailPage`.
  - Scoped TPS first, selectable metric overlays, service health, operations/APIs, recent changes, callers/dependencies, users, instances, traces, bandwidth, and access explorer.
- `/services/:name/apis/:api` -> `ApiDetailPage`.
  - API-level TPS/metrics, caller/user context, topology relationships, traces, and changes.
- `ServiceAccessBoard` and `AccessExplorer` provide the large-service access investigation surface.

### Users and identity intelligence

- `/users` -> `UserDirectory`.
  - Searchable identity inventory, risk/status filters, account type, requests, targets, callers, recent changes, and workspace launch.
- `/users/:principal` -> `UserLayout` with nested routes.
- `/users/:principal/activity` -> `UserActivityWorkspace`.
  - Combined Activity/Access workspace, TPS and baseline, KPI metric cards, charts, outcome view, activity heatmap, access relationships, and source-IP evidence.
- `/users/:principal/changes` -> `UserChangesTab`.
- `/users/:principal/changes/:episodeId` -> `UserChangeDetailPage`.
- `/users/:principal/overview`, `/topology`, `/patterns` -> compatibility redirects into Activity.
- `/users/:principal/investigations` -> compatibility redirect handled by `LegacyUserInvestigationRedirect`.
- `/unknown-users` -> `UnknownUsersPage` for unattributed/anonymous/public traffic; legacy anonymous user paths redirect here.

### Learned behavior and access

- `/behavior` -> `BehaviorPage`.
  - Learned behavior workspace, overview, profiles, deviations, and access Flow/Matrix tabs.
- `/behavior/profiles/:id` -> `BehaviorDetailPage kind="profiles"`.
- `/behavior/deviations/:id` -> `BehaviorDetailPage kind="deviations"`.
- `BehaviorAccess`, `AccessFlow`, `AccessMatrix`, `AccessExplorer`, and `AccessBoardColumn` implement the access projection.
- Access states are encoded consistently as established, emerging/learning, new, deviating, dormant, and ghost; observed vs baseline views are supported.

### Topology

- `/topology` -> `InteractiveTopologyPage`.
  - Full-canvas learned service topology, draggable cards, zoom/pan/reset, search, branch expansion, selected path highlighting, inspector, TPS trend, relationship/access drawer, and source/environment scope.
- `TopologyPage` remains a legacy/alternate topology implementation in source and is not the active route in `App.tsx`.

### Changes, alerts, and investigations

- `/changes` -> `ChangesPage`.
  - Episode list, filters, search, workflow/evaluation state, detector signals, priority, review status, and pagination.
- `/changes/:id` -> `ChangeDetailPage`.
  - Change context, metric comparison, visual evidence, timeline, path, related traces, operator decisions, and Jev/advisory investigation result.
- `/alerts` -> `AlertsPage`.
  - Alert rules, delivery history, retry controls, enable/disable/delete/create flows.
- `/anomalies` -> redirect to `/changes`.
- `/anomalies/:id` -> legacy anomaly/change redirect.

### Trace exploration

- `/traces` -> `TracesPage`.
  - Search/filter trace inventory and trace summaries.
- `/traces/:id` -> `TraceDetailPage`.
  - Multi-tier trace waterfall/details and related metadata.

### Agent fleet

- `/agent-stats` -> `AgentStatsPage`.
  - Fleet health, status, reason, latest samples, charts, and node list.
- `/agent-stats/:node` -> `AgentNodeDetailPage`.
  - Node detail/history, instance selection, telemetry charts, and delete actions.

### Legacy compatibility routes

- `/accounts`, `/accounts/:username` -> Users.
- `/principals`, `/principals/:name` -> Users.
- `/user-changes` -> Changes.
- `/user-analytics` -> Users.
- `Accounts.tsx`, `Principals.tsx`, `UserIntelligence.tsx`, `Anomalies.tsx`, and `Topology.tsx` retain compatibility/legacy UI implementations even where the active route now redirects or uses another page.

## 4. Shared UI primitives

`src/components.tsx` is the main shared visual primitive module:

- `Page`: standard page heading with eyebrow, title, description, and actions.
- `Panel`: bordered matte section with title, subtitle, and action slot.
- `Sparkline`: compact Recharts line sparkline with bounded sampling.
- `MetricCard` / `InteractiveMetricCard`: KPI value, detail, optional trend/sparkline, selected state.
- `TpsLineChart`: shared TPS/baseline chart behavior and completed-bucket handling.
- `Loading`: loading state.
- `ErrorState`: retry/error state.
- `RecentChangesPanel`: compact change list.
- Number/time helpers such as `n`, `pct`, `age`, and chart tooltip formatting.
- `ServicePerformancePanel`: reusable service metric presentation.

Other shared component modules:

- `components/EntityLink.tsx`: canonical links for Service, API, User, and Change entities.
- `components/EpisodePrimitives.tsx`: episode cards, status/workflow badges, timeline, evidence, path, metric table, baseline note, state labels, detector naming, filtering, and decision helpers.
- `components/ChangeVisualEvidence.tsx`: before/after change context chart and metric evidence.
- `components/InvestigationPanel.tsx`: investigation/advisory state, result, history, retry, and technical detail UI.
- `components/FleetTriage.tsx`: fleet table and service triage rows.
- `components/ZoomableDashboardChart.tsx`: chart viewport/zoom interaction.
- `components/ServiceAccessBoard.tsx`: service-scoped access entry point.
- `components/AccessBoardColumn.tsx`: reusable access list column.
- `components/AccessExplorer.tsx`: scalable service access explorer with unusual-now list, searchable/paged linked columns, selection panel, and direct neighbors.
- `components/AccessFlow.tsx`: Sankey-like flow, state encoding, filtering, item selection, hover portal, link simplification, inspector, and table mode.
- `components/AccessMatrix.tsx`: credential/API matrix with sorting, paging, state encoding, and keyboard interaction.

## 5. Access visualization model

`src/accessEncoding.ts` is the shared semantic encoding layer:

- Defines entity colors for service, credential/user, API, IP, and caller.
- Defines access states and state ordering.
- Provides labels, short labels, styles, IP-role labels, and normalization helpers.
- Ensures Flow, Matrix, topology, and service access views communicate the same state semantics.

`src/accessLayout.ts` contains deterministic layout logic:

- Responsive flow layout constants and geometry.
- Column placement and row compaction.
- Crossing reduction and barycenter sweeps.
- Compact mode for large cardinalities.
- Direct ribbon/link placement and node positioning.

Important interaction rules:

- Access ribbons are visual context; the selectable objects are the entity bars/items.
- Hover info is fixed-format and portalled, not a native tooltip.
- Clicking an item selects locally; filtering is an explicit action.
- Simplified mode reduces dense link bands; selected-item links remain fully visible.
- Service focus collapses the redundant Service column and preserves exact Credential -> API relationships.

## 6. Topology model and layout

`src/topologyLayout.ts` is the deterministic service-card placement engine:

- Group-first placement based on learned relationships.
- Connected components/community-aware positioning.
- Hub/neighbor attraction and canvas-aspect awareness.
- Rectangle collision checks and local spiral resolution.
- Deterministic output for stable redraws.
- Used by the active learned topology implementation in `InteractiveTopology.tsx`.

The active topology UI keeps graph rendering, card dragging, selection, zoom/pan, branch expansion, inspector, search, path highlighting, and access-flow entry in `InteractiveTopology.tsx`. It uses learned behavior read models rather than raw traces at request time.

## 7. API/data boundary

All frontend API calls should go through `src/api.ts`:

- `queryString()` serializes filters and normalizes ISO/epoch time values.
- Both `start`/`from` and `end`/`to` compatibility query keys are emitted.
- `api<T>()` adds `X-API-Key` when `VITE_API_KEY` is configured.
- Non-2xx responses become `ApiError` with status, code, and user-facing messages.
- Special messages exist for 401, unconfigured investigation auth/provider, and missing investigation resources.

Main frontend read-model families:

- Dashboard: `/api/v1/dashboard/summary`, `/api/v1/dashboard/series`.
- Services/APIs: `/api/v1/services`, `/api/v1/services/:service`, `/api/v1/apis`, topology service/API endpoints.
- Users/principals: `/api/v1/users`, `/api/v1/users/summary`, `/api/v1/principals`, user graph/analytics/change endpoints.
- Behavior: `/api/v1/behavior/topology`, `/api/v1/behavior/topology/detail`, `/api/v1/behavior/access`, `/api/v1/behavior/graph`.
- Changes/anomalies: `/api/v1/changes`, `/api/v1/changes/:id`, legacy anomaly endpoints, user-change review endpoints.
- Investigations: `/api/v1/investigations`, source/history/status/create endpoints.
- Topology/access: `/api/v1/topology`, `/api/v1/topology/services/...`, `/api/v1/topology/principals/...`, bandwidth and metrics endpoints.
- Traces: `/api/v1/traces`, `/api/v1/traces/:id`.
- Fleet/alerts/unknown traffic: agent stats, alerts/deliveries, and unknown-users endpoints.

## 8. Domain types

`src/types.ts` is the shared API-contract layer. It defines:

- Global filters, dashboard summary and series points.
- Topology `Edge` and `NodeItem`.
- Anomaly shape including baseline, current metrics, severity, root cause, blast radius, trace IDs, and dimensions.
- Re-exports investigation types from `src/investigations.ts`.

`src/investigations.ts` models source snapshots, finding references, eligibility, investigation lifecycle states, hypotheses, evidence, recommendations, assessments, result/history records, and create/retry payloads.

`src/investigationView.ts` converts backend investigation records into operator-facing view state.

`src/episodeActions.ts` centralizes episode decision rules and expected-state eligibility.

## 9. Visual system

The intended visual language is a compact Grafana-style operations console:

- Matte canvas: `#0b0c0e`.
- Panel/sidebar: `#111217`.
- Raised control: `#181b1f`.
- Hover surface: `#202226`.
- Border: `#2a2d30`; strong border: `#34373b`; grid: `#303236`.
- Text: `#f1f3f5`; secondary: `#c2c6cc`; muted/subtle: `#b8bcc4`.
- Blue/info: `#5794f2`.
- Green/success: `#73bf69`.
- Orange/warning: `#ff9830`.
- Red/critical: `#f2495c`.
- Yellow/selected: `#f2cc0c`.
- Purple/identity/secondary series: `#b877d9`.
- API/entity teal: `#56b9a8`.
- IP neutral: `#a7a9ab`.

Layout conventions:

- Prefer compact 2px/3px panel radii and crisp borders.
- Avoid glossy gradients, frosted glass, neon halos, and card shadows.
- Larger cards normally cap at two per desktop row; compact KPI cards may use four.
- Use responsive Tailwind grids, `min-w-0`, bounded scroll containers, and explicit mobile layouts.
- Keep operational statuses separate from entity identity colors.
- Do not imply a credential initiated traffic unless the evidence supports that claim; for system/shared credentials, show caller service -> target service -> API and attach identity/IP as evidence.

`src/index.css` contains the global token bridge, dark/light remapping, density rules, panel/control styles, chart stroke defaults, scrollbar rules, and compatibility remapping for older literal utility colors. `tailwind.config.js` mirrors the semantic colors and spacing/shadow tokens.

## 10. Localization

`src/i18n.tsx` contains:

- `I18nProvider`.
- `useI18n()` hook.
- `LanguageSwitcher`.
- English and Vietnamese translation dictionaries.
- Persistent language state and fallback behavior.

When adding UI:

1. Use `t("English key", "Vietnamese fallback")` for new visible copy.
2. Preserve protocol/product vocabulary such as Service, API, User, TPS, Latency, Trace, IP, Baseline, Agent, ClickHouse, and OTLP when operator recognition benefits.
3. Add both language entries when the string is a stable shared label.
4. Do not use color alone to communicate state.

## 11. Complete source file inventory

### Root configuration

- `frontend/index.html` — HTML shell, font loading, root mount, document metadata.
- `frontend/package.json` — scripts and runtime/build dependencies.
- `frontend/package-lock.json` — locked dependency graph.
- `frontend/vite.config.ts` — React plugin and `/api` development proxy to port 8000.
- `frontend/tailwind.config.js` — content globs, font families, semantic colors, shadow tokens.
- `frontend/postcss.config.js` — PostCSS/Tailwind processing.
- `frontend/tsconfig.json` — TypeScript project references.
- `frontend/tsconfig.app.json` — application compiler settings.
- `frontend/tsconfig.node.json` — Vite/config compiler settings.
- `frontend/tsconfig.app.tsbuildinfo` — generated TypeScript incremental state.
- `frontend/tsconfig.node.tsbuildinfo` — generated TypeScript incremental state.

### Application infrastructure and contracts

- `frontend/src/main.tsx` — React mount and provider composition.
- `frontend/src/App.tsx` — shell, navigation, global toolbar, contexts, route tree, compatibility redirects.
- `frontend/src/api.ts` — fetch wrapper, API key injection, query serialization, API errors.
- `frontend/src/types.ts` — shared API/domain types.
- `frontend/src/i18n.tsx` — localization provider, dictionaries, language switcher.
- `frontend/src/index.css` — global CSS, theme tokens, Tailwind layers, visual normalization.
- `frontend/src/vite-env.d.ts` — Vite environment type declarations.
- `frontend/src/entityRoutes.ts` — canonical Service/API/User/Change route builder.
- `frontend/src/episodeActions.ts` — change/episode operator decision helpers.
- `frontend/src/investigationView.ts` — investigation response-to-view mapping.
- `frontend/src/investigations.ts` — investigation data contracts and lifecycle helpers.

### Shared components

- `frontend/src/components.tsx` — core Page/Panel/KPI/chart/loading/error primitives.
- `frontend/src/components/AccessBoardColumn.tsx` — access board list column.
- `frontend/src/components/AccessExplorer.tsx` — scalable service access explorer.
- `frontend/src/components/AccessFlow.tsx` — flow/Sankey-style access visualization.
- `frontend/src/components/AccessMatrix.tsx` — access matrix visualization.
- `frontend/src/components/ChangeVisualEvidence.tsx` — change context metric chart.
- `frontend/src/components/EntityLink.tsx` — canonical entity navigation links/tokens.
- `frontend/src/components/EpisodePrimitives.tsx` — change episode UI and semantic labels.
- `frontend/src/components/FleetTriage.tsx` — service fleet triage table.
- `frontend/src/components/InvestigationPanel.tsx` — LLM/advisory investigation UI.
- `frontend/src/components/ServiceAccessBoard.tsx` — service access board container.
- `frontend/src/components/ZoomableDashboardChart.tsx` — zoomable dashboard chart.

### Semantic/layout helpers

- `frontend/src/accessEncoding.ts` — access states, colors, labels, and style encoding.
- `frontend/src/accessLayout.ts` — access flow geometry and large-cardinality layout.
- `frontend/src/topologyLayout.ts` — deterministic service topology layout.

### Active and compatibility pages

- `frontend/src/pages/Overview.tsx` — dashboard.
- `frontend/src/pages/Services.tsx` — service catalog and detail.
- `frontend/src/pages/ApiDetail.tsx` — API detail.
- `frontend/src/pages/Behavior.tsx` — learned behavior workspace/detail.
- `frontend/src/pages/BehaviorAccess.tsx` — behavior access tab composition.
- `frontend/src/pages/BehaviorGraph.tsx` — behavior graph view.
- `frontend/src/pages/Changes.tsx` — global changes list/detail.
- `frontend/src/pages/InteractiveTopology.tsx` — active learned topology canvas.
- `frontend/src/pages/Alerts.tsx` — alert rules and delivery management.
- `frontend/src/pages/Traces.tsx` — trace list/detail.
- `frontend/src/pages/AgentStats.tsx` — agent fleet/node detail.
- `frontend/src/pages/UnknownUsers.tsx` — unattributed traffic monitor.
- `frontend/src/pages/Accounts.tsx` — legacy account page compatibility surface.
- `frontend/src/pages/Anomalies.tsx` — legacy anomaly list/detail implementation.
- `frontend/src/pages/Principals.tsx` — legacy principal list/detail implementation.
- `frontend/src/pages/Topology.tsx` — legacy topology implementation.
- `frontend/src/pages/UserIntelligence.tsx` — legacy consolidated user intelligence implementation.

### User workspace pages

- `frontend/src/pages/user/UserDirectory.tsx` — identity directory.
- `frontend/src/pages/user/UserLayout.tsx` — user workspace shell/header/tabs.
- `frontend/src/pages/user/UserActivityWorkspace.tsx` — user activity and access workspace.
- `frontend/src/pages/user/UserChangesTab.tsx` — user changes list/detail and legacy investigation redirect.

## 12. Build and validation commands

From `frontend/`:

```sh
npm run lint
npm run build
```

`npm run build` runs `tsc -b` followed by `vite build`. The production SPA output is written to `frontend/dist/` and is served by the backend in the deployed application.

Do not hand-edit `frontend/dist/`, `frontend/node_modules/`, or TypeScript `.tsbuildinfo` files. Change source files, then rebuild.

## 13. Safe change checklist

Before changing a UI element:

- Identify whether it belongs to the global shell, shared primitive, active page, or compatibility page.
- Preserve URL-backed global filters and entity route conventions.
- Use `api()` and `queryString()` rather than ad-hoc fetch/query serialization.
- Keep React Query keys scoped to all request dimensions that affect the response.
- Preserve settled-bucket behavior for TPS charts; do not display open/incomplete buckets as final rates.
- Keep raw trace access out of request-time analytics UI; use backend read-model endpoints.
- Add localized strings through `useI18n()`.
- Preserve keyboard focus, `aria-label`, `aria-pressed`, and visible focus rings for controls.
- Test both dark/light themes and 1440px/390px responsive layouts.
- Run `npm run lint`, `npm run build`, and the relevant browser/API smoke tests.
- Run `git diff --check` after editing.
