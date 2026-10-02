# TraceScope Light Mode — Deep Redesign Plan

## Objective

Replace the current light-mode implementation—which primarily remaps dark-mode literal utility classes through broad CSS selectors—with a deliberate, first-class light operational workspace.

The redesign should feel like a professional observability console rather than a dark UI placed on a white canvas:

- Strong information hierarchy without glare.
- Clear separation between canvas, navigation, panels, controls, tables, overlays, and charts.
- Stable semantic colors for healthy, warning, critical, selected, identity, and topology states.
- High readability for dense telemetry tables and long investigation sessions.
- Visual parity with dark mode in capability, not identical colors or contrast behavior.
- No regressions to topology, access-flow, chart, interaction, or mobile layouts.

## Current-state diagnosis

The current light mode is implemented mainly in `frontend/src/index.css` through selectors such as:

- `html[data-theme="light"] [class*="bg-[#"]`
- `html[data-theme="light"] [class*="text-[#"]`
- `html[data-theme="light"] [class*="border-[#"]`
- Broad remapping of older literal Tailwind classes.

This creates several problems:

1. **Semantic loss:** unrelated surfaces sharing a literal dark color become the same light color.
2. **Specificity fragility:** `!important` rules are required to override page-level utility classes.
3. **Poor component ownership:** visual intent is hidden in CSS selectors instead of component tokens.
4. **Inconsistent light hierarchy:** panels, raised controls, table rows, popovers, topology cards, and drawers do not have enough distinct surfaces.
5. **Chart risk:** Recharts, ECharts, SVG topology, access ribbons, and inline style colors are not governed by one complete light palette.
6. **Status confusion:** identity colors and operational severity colors can lose contrast or become too similar on white backgrounds.
7. **Legacy drift:** active pages, compatibility pages, and large visual components use several generations of hard-coded colors.
8. **Maintenance cost:** every new dark literal requires another light-mode exception.

The redesign must preserve the existing dark theme while changing the architecture from **literal-color remapping** to **semantic token consumption**.

## Design direction

### Concept: daylight operations console

Use a cool, low-glare neutral foundation with restrained blue telemetry accents:

- Canvas: very light blue-gray, not pure white.
- Navigation: white with a slightly stronger elevation boundary.
- Panels: white and near-white layered surfaces.
- Controls: cool gray raised surfaces with visible boundaries.
- Data density: compact rows, strong column alignment, muted dividers.
- Primary telemetry: deep accessible blue rather than saturated neon blue.
- Status: green/orange/red with dark text or strong accessible fills.
- Identity: purple for credentials/users, teal for APIs, blue for services, neutral gray for IPs.
- Selection: blue outline/fill rather than yellow-only selection.

Suggested visual character:

- Background #f3f6fa.
- Navigation #ffffff.
- Surface #ffffff.
- Raised surface #f8fafc.
- Muted surface #edf2f7.
- Stronger selected surface #e8f0ff.
- Border #d5dee9.
- Strong border #b9c7d8.
- Primary text #172235.
- Secondary text #43536a.
- Muted text #64748b.
- Subtle text #8290a3.

These are starting values, not final approved tokens; they must be validated against real screenshots and contrast checks.

## Token architecture

### 1. Define semantic theme tokens

Extend the root theme model in `frontend/src/index.css` with explicit semantic roles rather than only generic surface names.

```css
:root {
  --theme-canvas: ...;
  --theme-sidebar: ...;
  --theme-surface: ...;
  --theme-surface-raised: ...;
  --theme-surface-muted: ...;
  --theme-surface-selected: ...;
  --theme-surface-hover: ...;
  --theme-surface-inset: ...;
  --theme-overlay: ...;

  --theme-border: ...;
  --theme-border-strong: ...;
  --theme-border-focus: ...;
  --theme-divider: ...;

  --theme-text: ...;
  --theme-text-secondary: ...;
  --theme-text-muted: ...;
  --theme-text-subtle: ...;
  --theme-text-inverse: ...;

  --theme-info: ...;
  --theme-info-surface: ...;
  --theme-success: ...;
  --theme-success-surface: ...;
  --theme-warning: ...;
  --theme-warning-surface: ...;
  --theme-danger: ...;
  --theme-danger-surface: ...;
  --theme-selected: ...;
  --theme-selected-surface: ...;

  --theme-service: ...;
  --theme-credential: ...;
  --theme-api: ...;
  --theme-ip: ...;
  --theme-caller: ...;
}
```

Use separate `--theme-*` values for dark and light modes. Do not reuse the dark literal palette as the source of truth for either mode.

### 2. Add component tokens

Define reusable component-level tokens for:

- App rail.
- Toolbar.
- Panel.
- Card.
- Metric card.
- Button variants.
- Input/select states.
- Table header/row/hover/selected states.
- Badge and status pills.
- Tooltip/popover/drawer.
- Chart grid/axis/tooltip/cursor.
- Topology node/edge/inspector.
- Access-flow state styles.

This allows light mode to differ intentionally without adding page-specific selectors.

### 3. Update Tailwind semantic colors

Update `frontend/tailwind.config.js` to expose semantic variables instead of encouraging literal arbitrary colors:

- `bg-canvas`, `bg-surface`, `bg-raised`, `bg-muted`, `bg-selected`.
- `border-default`, `border-strong`, `border-focus`.
- `text-primary`, `text-secondary`, `text-muted`, `text-subtle`.
- `status-info`, `status-success`, `status-warning`, `status-danger`.
- `entity-service`, `entity-credential`, `entity-api`, `entity-ip`.

Keep legacy literal support temporarily during migration, but mark it as compatibility-only.

## Component migration plan

### Phase 1 — Theme foundation

Files:

- `frontend/src/index.css`
- `frontend/tailwind.config.js`
- `frontend/src/App.tsx`
- `frontend/src/components.tsx`

Work:

1. Replace the current large light-mode literal remapping block with semantic variables and a small compatibility bridge.
2. Add `data-theme`-aware native control styling for `input`, `select`, `button`, `option`, and scrollbars.
3. Create consistent focus, hover, active, disabled, selected, loading, and error states.
4. Normalize panel/card/toolbar/table primitives in `components.tsx` and CSS component classes.
5. Add `color-scheme`, `accent-color`, selection color, and print-safe defaults.
6. Ensure theme transition does not flash or animate data visualizations unexpectedly.

Acceptance:

- No pure-white text remains on a light background unless it is inside a verified dark accent control.
- No light-mode component depends on a page-specific `!important` override for normal operation.
- Core contrast passes WCAG AA for text and controls.

### Phase 2 — Application shell redesign

Files:

- `frontend/src/App.tsx`
- `frontend/src/i18n.tsx`
- `frontend/src/index.css`

Work:

#### Side navigation

- White navigation rail with a subtle right boundary and optional shadow/elevation.
- Brand mark uses a blue/indigo accent block with accessible white icon treatment.
- Active item uses a pale blue selected surface, deep blue icon, and a 3px leading accent bar.
- Inactive item uses readable slate text, not gray-on-white.
- Section labels use compact uppercase slate text with colored dots.
- Click/hover areas remain at least 32–36px high.
- Expanded rail state must not create a layout jump or obscure content.

#### Toolbar

- Use a distinct toolbar surface from the page canvas.
- Make the current entity breadcrumb darker and more prominent.
- Search field receives a white/inset field treatment with clear focus ring.
- Filter button uses a neutral default and blue selected state.
- Live status should use a green dot and pale green surface, not fluorescent green text.
- Theme toggle should visibly communicate the current mode.
- Time window badge should be informational blue, not a competing primary action.

#### Mobile shell

- Add a mobile header/menu affordance if the existing hidden rail leaves navigation inaccessible.
- Keep search, refresh, theme, and language controls reachable without horizontal overflow.
- Ensure toolbar wrapping does not push content below the fold excessively.

Acceptance:

- Shell screenshots at 1440px, 1024px, 844px, and 390px.
- Keyboard navigation visibly identifies active/focused navigation and toolbar controls.
- No horizontal document overflow.

### Phase 3 — Shared primitives and controls

Files:

- `frontend/src/components.tsx`
- `frontend/src/components/EpisodePrimitives.tsx`
- `frontend/src/components/EntityLink.tsx`
- `frontend/src/components/InvestigationPanel.tsx`
- `frontend/src/components/FleetTriage.tsx`

Work:

- `Page`: improve heading scale, eyebrow contrast, title/description spacing, and action grouping.
- `Panel`: establish white surface, crisp border, subtle header tint, and consistent divider.
- `MetricCard`: use a neutral card with a colored metric marker, not a fully color-washed card.
- `InteractiveMetricCard`: selected state should be a blue outline + pale blue surface; preserve status color only for the metric identity.
- `Loading`: use skeletons with light gray shimmer/solid blocks; avoid low-contrast pulsing.
- `ErrorState`: use pale red surface, deep red icon/text, and clear retry button.
- `EntityLink`: ensure entity colors remain readable and distinguishable on white.
- Episode/status badges: remove unnecessary boxed appearance where appropriate, but preserve a visible status cue through icon + text + accessible color.
- Investigation cards: separate result state, provider state, and operator action with clear surface hierarchy.
- Tables: improve row hover, selected row, sticky header, sort indicator, empty state, and pagination controls.

Acceptance:

- Every shared primitive works in both themes without hard-coded theme assumptions.
- Status remains understandable in grayscale through text/icons, not color alone.
- Focus rings are visible on white and pale-blue surfaces.

### Phase 4 — Dashboard and analytical pages

Files:

- `frontend/src/pages/Overview.tsx`
- `frontend/src/pages/Services.tsx`
- `frontend/src/pages/ApiDetail.tsx`
- `frontend/src/pages/AgentStats.tsx`
- `frontend/src/pages/UnknownUsers.tsx`

Work:

- Establish a consistent page canvas and panel grid.
- Use distinct neutral surfaces for KPI strip, main charts, secondary charts, and tables.
- Increase chart plot/background separation without adding heavy boxes.
- Keep chart grid lines subtle but visible in light mode.
- Make axis labels slate, tooltip surfaces white with strong border and shadow/elevation.
- Use a consistent chart palette with tested contrast:
  - TPS/primary: deep blue.
  - Baseline: slate or purple dashed/secondary line.
  - Success: deep green.
  - Warning: ochre/orange.
  - Error: deep red.
  - Bandwidth: teal.
- Ensure chart fills use low-opacity tinted areas, not opaque saturated fills.
- Preserve completed-bucket logic and no-data states.
- Make abnormal-score distribution readable against pale backgrounds.
- Tables should use alternating semantic row states only where needed; avoid zebra noise in dense views.

Acceptance:

- Compare dark/light screenshots using the same data fixtures.
- Verify tooltips, legends, reference lines, selected cards, empty states, and error states.

### Phase 5 — Topology and access visualizations

Files:

- `frontend/src/pages/InteractiveTopology.tsx`
- `frontend/src/pages/Topology.tsx`
- `frontend/src/components/AccessFlow.tsx`
- `frontend/src/components/AccessMatrix.tsx`
- `frontend/src/components/AccessExplorer.tsx`
- `frontend/src/components/ServiceAccessBoard.tsx`
- `frontend/src/components/AccessBoardColumn.tsx`
- `frontend/src/accessEncoding.ts`
- `frontend/src/accessLayout.ts`
- `frontend/src/topologyLayout.ts`

Work:

#### Topology canvas

- Replace dark canvas assumptions with a light grid/neutral canvas token.
- Use subtle gray-blue relationship lines, blue selected lines, and sufficient contrast for arrows.
- Node cards use white surfaces with entity-specific accent rails or icons, not full saturated backgrounds.
- Selected nodes use a blue outline and pale blue fill.
- Inspector becomes a white elevated drawer with a stronger border and controlled shadow.
- Search, zoom, reset, history, and legend controls use the shared control tokens.
- Preserve drag, pan, zoom, keyboard selection, branch expansion, and full-canvas click behavior.

#### Access Flow

- Establish state styles specifically for light backgrounds:
  - Established: solid dark slate/blue-green.
  - Learning/emerging: patterned or dashed blue-gray.
  - New/deviating: orange with icon/glyph and strong text.
  - Ghost/dormant: dotted muted slate.
- Keep ribbons visually subordinate to selectable entity bars.
- Use a white tooltip/inspector with explicit state label, observed/expected TPS, and last-seen metadata.
- Ensure simplified bands remain visible on light backgrounds.
- Keep entity color semantics distinct from operational state colors.

#### Access Matrix/Explorer

- Use crisp grid dividers and selected row/column tints.
- Provide a stronger focus outline for keyboard navigation.
- Ensure large matrices remain legible without relying on dark fills.
- Preserve dense layout, paging, search, and direct-neighbor selection behavior.

Acceptance:

- Synthetic dense cases: 50x50 and 600x150/large relation data.
- Validate selected, hovered, simplified, ghost, deviating, and empty states in light mode.
- Confirm SVG/canvas labels and lines remain legible at 390px width.

### Phase 6 — Changes, alerts, traces, and user workspace

Files:

- `frontend/src/pages/Changes.tsx`
- `frontend/src/pages/Alerts.tsx`
- `frontend/src/pages/Traces.tsx`
- `frontend/src/pages/user/UserDirectory.tsx`
- `frontend/src/pages/user/UserLayout.tsx`
- `frontend/src/pages/user/UserActivityWorkspace.tsx`
- `frontend/src/pages/user/UserChangesTab.tsx`
- `frontend/src/pages/UserIntelligence.tsx`
- `frontend/src/pages/Anomalies.tsx`
- `frontend/src/pages/Principals.tsx`
- `frontend/src/pages/Accounts.tsx`

Work:

- Changes list: use a neutral table/list canvas with strong orange/red semantic markers; avoid red/orange whole-row fills.
- Change detail: make metric evidence, timeline, path, and investigation sections visually distinct.
- Review status and priority must remain separate dimensions.
- Alerts: separate rule configuration panels from delivery history and retry actions.
- Traces: use white detail panels, gray waterfall lanes, blue selected span, and status-specific markers.
- User directory: improve risk badges and active/inactive state contrast.
- User workspace: provide a clear hierarchy between identity header, scoped KPI ribbon, Activity/Changes tabs, and evidence panels.
- Unknown traffic: amber identity-attribution context should be distinct from authentication failure red.
- Compatibility pages should receive the token migration where they remain reachable; avoid leaving visually broken legacy screens.

Acceptance:

- Verify operational status, review status, severity, and identity type are distinguishable without color alone.
- Verify long names, trace IDs, API paths, and localized Vietnamese text do not break layout.

## Data visualization rules for light mode

1. Every chart must define explicit light-theme colors rather than inheriting browser/SVG defaults.
2. Axis labels must meet readable contrast against the chart background.
3. Grid lines should be visible but subordinate; target roughly 10–20% neutral contrast.
4. Tooltips must have an opaque surface, strong border, and readable shadow/elevation.
5. Avoid using yellow as the only selected-state signal; pair it with outline and label.
6. Filled areas should use low-opacity tints and retain a strong line.
7. Dashed baselines must remain distinguishable from grid lines.
8. Null/missing data must remain visually distinct from zero.
9. Dense topology/access lines must not disappear against `#f3f6fa`.
10. Validate color-blind distinguishability for blue/teal/purple and green/orange/red pairs.

## Implementation strategy

### Recommended order

1. Add semantic tokens and component token layer.
2. Refactor shared primitives.
3. Refactor shell and controls.
4. Refactor chart theme helpers.
5. Refactor topology/access encoding.
6. Migrate active pages in product priority order.
7. Migrate compatibility pages.
8. Remove obsolete broad literal remapping selectors.

### Suggested new modules

- `frontend/src/theme.ts` — typed semantic color palette and chart colors for dark/light.
- `frontend/src/theme.css` or a dedicated token section in `index.css` — CSS variable definitions only.
- `frontend/src/chartTheme.ts` — Recharts/ECharts/SVG chart colors, axis/grid/tooltip settings.
- Optional `frontend/src/components/StatusBadge.tsx` — unified status/severity treatment if existing episode primitives are not sufficient.

Use CSS variables for DOM/CSS and a typed TypeScript palette for inline SVG, ECharts, and Recharts props. Do not duplicate color literals across page files.

### Migration rule

For each changed component:

1. Replace literal background/text/border classes with semantic classes or CSS variables.
2. Remove page-specific light-mode overrides for that component.
3. Define hover/focus/selected/disabled states together.
4. Test dark mode immediately after the change.
5. Test light mode with realistic data and empty/error/loading states.

## Accessibility requirements

- WCAG AA for normal text and controls; target AAA for dense muted labels where practical.
- Never use color alone for severity, access state, review status, or identity type.
- All icon-only buttons require an accessible label and useful tooltip/title.
- Visible `:focus-visible` outlines must be present on every interactive element.
- Minimum pointer target: 32px for compact desktop controls; 40px where feasible on mobile.
- Native selects/options must remain readable under light color scheme.
- Respect `prefers-reduced-motion` for theme transitions, loading states, topology movement, and chart transitions.
- Preserve keyboard operation for navigation, table sorting, access matrix, topology selection, and drawers.
- Check Vietnamese text expansion and screen-reader labels.

## Validation plan

### Static validation

```sh
cd frontend
npm run lint
npm run build
cd ..
git diff --check
```

### Automated UI checks

Run the existing project checks after the redesign:

- `sh backend/scripts/curl_test_all_pages.sh`
- `python3 backend/scripts/test_pages_playwright.py`
- Relevant access/topology/frontend tests already present in the repository.

### Theme matrix

Test every active route in:

- Dark / light.
- English / Vietnamese.
- 1440px desktop.
- 1024px tablet/small desktop.
- 844px mobile landscape/tablet.
- 390px mobile portrait.

### State matrix

For representative pages, validate:

- Loading.
- Loaded with dense data.
- Empty/no telemetry.
- API error/retry.
- Selected/hovered/focused.
- Disabled controls.
- Long labels/API paths/trace IDs.
- Open/critical/resolved/expected changes.
- Established/emerging/new/deviating/dormant/ghost access states.
- Topology zoom/drag/inspector/drawer.

### Visual regression targets

Capture and compare before/after screenshots for:

1. Global shell and toolbar.
2. Dashboard.
3. Service detail.
4. User Activity.
5. Changes detail.
6. Interactive topology.
7. Access Flow and Access Matrix.
8. Agent Fleet.
9. Unknown Users.
10. Trace detail.

## Definition of done

- Light mode has an intentional semantic token system, not broad literal color overrides as its primary mechanism.
- All active routes are visually coherent in light mode.
- Shared components, charts, topology, access visualizations, tables, drawers, and tooltips have dedicated light states.
- Dark mode remains visually stable and functionally unchanged.
- No horizontal overflow at supported breakpoints.
- No inaccessible white-on-white or low-contrast status/control states.
- Existing API contracts, filters, routing, query behavior, and telemetry semantics are unchanged.
- Build, lint, diff checks, page smoke tests, and browser checks pass.
- Obsolete compatibility remapping rules are removed or isolated with clear comments.
