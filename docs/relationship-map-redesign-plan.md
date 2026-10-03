# Relationship map and Changes redesign: implementation plan

Status: approved direction (2026-10-03), not started. Written for an agent that has not seen the
design discussion. Read the whole file before editing code.

Design reference (prototypes on a mocked 240-service estate):
- **In the repo (read this, it is the source of truth):** `docs/prototypes/relationship-map-concepts.html`.
  Open it in a browser (`file://`) or read the code. It is plain HTML + vanilla JS, no build step.
  The parts that matter:

  | Concept | Used for | CSS (line) | JS (line) |
  |---|---|---|---|
  | **C · Attention feed** | layout of the `/changes` list | `/* C: feed */` (~156) | `renderFeed()` (~788), click handlers right after it |
  | **A · Anchor explorer** | main area of `/workspace/map` | `/* A: anchor explorer */` (~103) | `SIDES` (~489), `goAnchor` (~501), `connector` (~522), `sideHTML` (~533), `renderAnchor` (~549) |
  | **D · Reach icicle** (search + list only) | left rail of `/workspace/map` | `.ulist`, `.urow` in `/* D: icicle */` (~180) | list part of `renderReach()` (~857), `wireSearch()` (~616) |

  Concept B (heatmap) and the icicle drawing itself are not built. The mocked data generator
  (~323-420) is only for the prototype; the real pages use the APIs listed below.
- Published copy (same file, may need the owner to share it): https://claude.ai/artifact/AtKge2SykdNkybua2sv1QQ

What to build:
- `/changes`: keep the data (change **episodes** from `GET /api/v1/changes`) and the detail page;
  redesign the **list page** in the layout of concept C. No new backend endpoint.
- `/workspace/map`: rewrite as concept A (anchor explorer) with D's search bar and list as its left rail.

## 1. Why

`/workspace/map` today (`frontend/src/workspace/MapPage.tsx`, backend `GET /api/v1/relationships/graph`)
draws a Sankey of up to five columns with the top N nodes per column. With 200+ services it either
hides most services in an "Other" node ("Show 15": ~94% of services folded away) or becomes
unreadable ("Show 60": 244 nodes, 832 ribbons). The rule for the new design: **never more than
about 30 entities on screen; complexity is limited by choosing an anchor, not by a top-N cut of
everything.**

## 2. Ground rules (from AGENTS.md, apply to every step)

- Start each reply to the user with the line required by Rule xHatsu in AGENTS.md.
- Shell: POSIX `sh` only. Never run `kubectl`.
- Never run two pytest sessions at the same time against the same ClickHouse
  (`tests/conftest.py` drops every `test_*` database when a session ends).
  Run tests with `set -a && . ./.env && set +a && .venv/bin/python -m pytest <files> -q`.
- ClickHouse: never give an alias the same name as a column it aggregates
  (`sum(rb) AS rb` returns wrong values / ILLEGAL_AGGREGATION). Read `topology_principal_ip_5m` with `FINAL`
  (already done inside `_base_sql`).
- Read only `topology_principal_ip_5m` (via the helpers in `backend/app/api/relationships.py`).
  User-facing APIs must not read raw `traces` (`tests/test_api_read_model_boundary.py` enforces this).
- Unknown users: principals `''`, `unknown`, `-anonymous-`, `anonymous` are one bucket,
  canonicalised to `-anonymous-` (`ANONYMOUS_SQL`). They never appear as a user row.
- API names exist in two spellings (`METHOD /path` and `service/METHOD /path`); `_base_sql`
  already normalises them. Always key an API by `(service, api)`.
- Frontend: semantic tokens only (`text-entity-user`, `bg-accent-soft`, `var(--warn)`, ...),
  no hex or Tailwind palette colours; run `frontend/scripts/check-color-budget.sh` (must stay 15/15 ok).
  Copy goes through `t(en, vi)`; add Vietnamese for every new string.
- React Router drops back-to-back `setSearchParams` calls: change several URL params in one update
  (see `useSelection().focus` in `frontend/src/workspace/model.ts`).
- Do not commit or push unless the user asks.
- When done, add a section to AGENTS.md (newest first) and STATE.md describing what changed and how it was verified.

## 3. Existing pieces to reuse

| Piece | Where | Use |
|---|---|---|
| `GET /api/v1/relationships` | `backend/app/api/relationships.py` | Every side list of the anchor explorer. Scope `principal` / `service` / `api(+service)`, selection `sel_*` (incl. `sel_group`), `facets=caller,principal,service,api,ip,unknown_ip`, `q`, `limit<=1000`, `from`/`to`. Each row has `requests`, `prev_requests`, `state` (`new|active|silent`), `principals`, `unknown_requests`, `callers`, `apis`, `services`, catalog `environment/group/module`. |
| `useRelationships`, `useSelection`, `windowParams`, `workspacePath`, `formatTps`, `StateBadge`, `entityTone` | `frontend/src/workspace/{model.ts,parts.tsx}` | Data hooks, URL state, links to the User / API / Service workspace pages. |
| `ServiceFilterBar` | `frontend/src/workspace/ServiceFilter.tsx` | Not needed on the map any more (the anchor bounds the size). Keep the file; other workspace pages use it. |
| Changes page | `frontend/src/pages/Changes.tsx` | List page redesigned (Part A); detail page untouched. |

"New / silent" needs a full previous window. The response field `window.history_available`
says whether the rollup covers it; when it is false, `state` is never `new`. The rollup started
around 2026-10-01, so 7-day windows have no history yet; 24-hour windows do.

## 4. Part A: `/changes` list in the concept C layout

Scope: only `ChangesPage` in `frontend/src/pages/Changes.tsx`. `ChangeDetailPage`, the
`/api/v1/changes` API, episode evaluation, operator decisions and the AI assessment stay as they are.
Every filter, sort, URL param and count the page has today must still work (same param names:
`view`, `subject`, `change_type`, `assessment`, `q`, `sort`), so existing links keep working.

Data: `GET /api/v1/changes?<window>&limit=500` (type `EpisodeResponse` / `Episode` in
`frontend/src/components/EpisodePrimitives.tsx`). Useful fields: `subject {type,name}`, `state`
(`critical|needs_attention|watch|changed|expected`), `status`, `summary`, `context {caller,target,operation,source_ip}`,
`highlights[] {label,before,after,unit}`, `signal_count`, `last_seen_at`, `started_at`,
`semantic_assessment`. Helpers to reuse: `changeTypes`, `changeTypeLabel`, `episodeTitle`,
`episodeMatchesView`, `episodeSearchText`, `EpisodeStatusBadge`, `EpisodeWorkflowBadge`,
`SemanticAssessmentBadge`, `formatHighlightDelta`, `formatEpisodeTime`, `EntityLink`, `entityPath`.

### 4.1 Layout (three columns from `xl`, one column below; see prototype C)

```
┌ left rail (200px) ───┐┌ list ─────────────────────────────────────┐┌ right (280px) ──────┐
│ VIEW                  ││ [search……………]  [Priority first ▾]           ││ WHERE CHANGES ARE   │
│ ○ Needs attention  12 ││ 37 changes · ranked by priority            ││ [Group|Service|User]│
│ ○ All              40 ││ ─────────────────────────────────────────── ││ order-service  ▇▇ 9 │
│ ○ Reviewed          3 ││ [CRITICAL][Open] order-service: Traffic…    ││ alice_wsse     ▇  4 │
│ CHANGE TYPE           ││  summary line                               ││ …                   │
│ ☑ Traffic spike     5 ││  traffic-ui → order-service → POST /x       ││ (click = filter)    │
│ ☑ New service rel.  3 ││  before ▁ 0.41 TPS / now ▇ 4.71 TPS         ││                     │
│ …                     ││  [AI: Investigate]  last seen 10:42         ││                     │
│ SUBJECT  ○All ○Svc ○U ││  View details · Investigate · Explore map → ││                     │
│ AI ASSESSMENT ▾       ││ ─────────────────────────────────────────── ││                     │
│ Clear filters         ││ … 25 per page, pager at the bottom          ││                     │
└───────────────────────┘└─────────────────────────────────────────────┘└─────────────────────┘
```

- **Left rail** (prototype `.rail`): replaces today's tab row and dropdowns.
  - View: Needs attention / All / Reviewed as a radio list with counts (today's tab buttons and counts).
  - Change type: checkbox list of every type in the loaded episodes with counts and the type label
    (`changeTypeLabel`). Today the param holds one type; change `change_type` to accept a
    comma-separated list (one type still parses the same), empty = all.
  - Subject: All / Service / User. AI assessment: keep today's `<select>` with the same options.
  - Critical count (today in the tab row) moves to the top of the rail.
  - "Clear filters" when any filter is set. Below `xl` the rail becomes a wrapping row of compact controls.
- **List** (prototype `.finding`): one row per episode, no table header.
  - Line 1: `EpisodeStatusBadge` + `EpisodeWorkflowBadge` as chips, then the title (`episodeTitle`,
    link to the detail page with the current filters as today's `detailSearch`).
  - Line 2: `summary` (one line, muted, truncated).
  - Line 3: path as entity chips joined by arrows: caller → subject / target service → operation,
    plus source IP when present; colours `text-entity-service`, `text-entity-user`, `text-entity-api`,
    `text-entity-ip`. Build it from `subject` + `context`, the same order as `EpisodePath`.
  - Type chips (click = add that type to the filter), signal count, `SemanticAssessmentBadge` when evaluated.
  - Right column: before / now mini bars with values from the first highlight that has numeric
    `before` and `after` (bar lengths relative to the larger of the two; `unit` from the highlight;
    use `formatHighlightDelta` for the delta). When there is none, show "See evidence". Last seen time under it.
  - Actions: **View details**, **Investigate** (detail page `#ai-investigation`, as today), and
    **Explore on map →** linking to `/workspace/map` with the Part B anchor: user subject → user anchor;
    service subject with `context.operation` → API anchor (`anchor_service` = target or subject);
    otherwise service anchor; set `scope_user` when both a user and a service/API are known.
  - Sort: Priority first (today's `rank` then last seen) / Latest first. 25 per page with the same pager text as today.
- **Right panel "Where changes are"** (prototype "Estate by group" table):
  - Segmented control Group | Service | User. Group uses the catalog group of the episode's service
    (`subject.name` for service subjects, else `context.target`) from `GET /api/v1/services?limit=500`
    (`service_group`; missing = "Core"). Hide the Group option when all services share one group
    (true on live data today) and default to Service.
  - Each row: name, bar, number of matching episodes, number still needing attention. Click = filter
    (`where=<kind>:<name>` URL param, shown as a removable chip in the rail).
- Empty state, loading and error: reuse `Loading` / `ErrorState`; keep "No changes match the selected view."
- Below `xl` the right panel moves under the list.

### 4.2 Checks for this part

- Every existing URL (`/changes?view=all&subject=user&change_type=traffic_spike&q=x&sort=recent`)
  opens with the same filters applied, and links from the dashboard and the User Changes tab still work.
- Counts in the rail equal the number of rows shown after applying that one filter.
- `/changes/:id` is unchanged (visual diff not needed, just open one).

## 5. Part B: anchor explorer on `/workspace/map` (concept A + D's list)

Replace the contents of `frontend/src/workspace/MapPage.tsx` (keep the export name
`RelationshipMapPage` and the route). Delete the flow/matrix code, `useGraph`, `layoutFlow`, etc.

### 5.1 Layout

```
┌ left rail (260px) ─────────┐┌ main ───────────────────────────────────────────────┐
│ [search: user, API, service]││ breadcrumb: alice › billing-api › POST /x            │
│ [Users | APIs | Services]  ││ [Only traffic from alice ×]                           │
│ All traffic                ││ ┌ left side ─┐  ╲   ┌ centre ─┐   ╱  ┌ right side ─┐ │
│ Unknown users              ││ │ ≤10 rows   │ ──── │ KPIs     │ ──── │ ≤10 rows    │ │
│ alice_wsse        12 svc   ││ │ +N more ▾  │  ╱   │ chips    │   ╲  │ +N more ▾   │ │
│ bob_wsse          11 svc   ││ └────────────┘      └──────────┘      └─────────────┘ │
│ … (sorted by reach)        ││ legend                                               │
└────────────────────────────┘└──────────────────────────────────────────────────────┘
```

Below `lg` the rail sits above the main area (list max-height ~200px); below `md` the three
columns stack (centre first) and the connector SVGs are hidden. No horizontal page overflow at 390 px.

### 5.2 Left rail (from concept D)

- Search input: debounced (250 ms) server search through `/relationships` with `q=<text>`,
  `facets=principal,service,api`, `limit=8`; one result list with kind chips (catalog groups whose name matches come first, from `service_meta_options.group`). Enter picks the
  highlighted result; arrows move; Escape clears.
- Kind switch **Users | APIs | Services** (default Users), URL `list=`:
  - Users: `/relationships?facets=principal&limit=1000`, sorted by `services` desc then `requests`
    (that is "reach"); each row shows name and `N svc`. Fixed entries on top: **All traffic**
    and **Unknown users** (warn colour).
  - APIs: `facets=api`, sorted by requests; shows `service` as a second line and the unknown share.
  - Services: `facets=service`, sorted by requests; shows group · module.
  - Rows render virtualised or capped at 300 with "type to search"; filter the loaded list
    client-side as the user types, and fall back to server `q` when the list was truncated.
- The selected anchor is highlighted (`aria-pressed`).

### 5.3 Anchor kinds and data

URL: `anchor_kind`, `anchor`, `anchor_service` (APIs only), `scope_user`, `trail` (optional,
encoded list for the breadcrumb, max 6). All in one `setSearchParams` call per click.
Default when nothing is set: **All traffic**.

| Anchor | Request (`/relationships`) | Left side | Right side | Centre extras |
|---|---|---|---|---|
| All traffic | no scope, `facets=caller,service` | Called from: caller services (incl. "No caller service" row, not clickable) | Services | top users chips (`principal` facet limit 6), unknown share |
| User | `principal=<u>`, `facets=caller,service,api` | Comes through: caller services | Reaches: services | top APIs chips |
| Unknown users | `principal=-anonymous-`, `facets=caller,api,unknown_ip` | Comes through: caller services | APIs | top source IPs chips (`unknown_ip`) |
| Service | `service=<s>`, `facets=caller,api,principal` (+ `sel_principal=<scope_user>`) | Called by: caller services | Serves: APIs | top users chips, unknown share |
| API | `service=<s>&api=<a>`, `facets=principal,caller` (+ `sel_principal`) | Used by: users (+ one "Unknown users" row from `summary.unknown_requests`, clickable → Unknown users anchor) | Called through: caller services | unknown share, link to the API workspace page |
| Group (from search: match the typed text against `service_meta_options.group` of the same response) | `sel_group=<g>`, `facets=caller,service` | Called from: caller services, grouped by their catalog group in the client | Services | top users |

- Side rows: dot in entity colour, name (+ second line: group · module for services, service for
  APIs), traffic bar, requests, `StateBadge` for new/silent, plus a "surge" chip when
  `prev_requests > 0 && requests / prev_requests >= 2.5`. Sort by `max(requests, prev_requests)`
  so silent rows are not lost. Show 10; "+ N more" opens an in-place filterable list (all rows the
  request returned; if `truncated`, re-query with `q`).
- Connectors: plain SVG between each side and the centre, one cubic path per visible row
  (fixed row height, so no DOM measuring), width `1.2 + 7·share`; colour: new = accent,
  surge = warn, silent = bad dashed, others `--border-strong`. Hover a row thickens its path.
- Centre card: kind eyebrow, name (mono), requests in window, change vs previous window
  (or "new"), unknown share (not for users), counts per side, extra chips, and
  **Open page** linking to `workspacePath.user/api/service`.
- Clicking a row moves the anchor there (push the old anchor on `trail`). If the old anchor is a
  user and the new one is a service or API, set `scope_user` to that user ("Only traffic from X",
  removable chip); anchoring on a user clears `scope_user`. "No caller service" rows are not clickable.
- Breadcrumb buttons restore an earlier anchor (and its `scope_user`).
- Loading: keep previous data (`keepPreviousData`) and dim the main area; errors use `ErrorState`.

### 5.4 Remove the old graph

After the new page works: delete `GET /api/v1/relationships/graph` and its helpers
(`GRAPH_COLUMNS`, `GRAPH_KEY_SQL`, `_graph_key`, `_graph_node`, `OTHER`, `NO_CALLER`) and the two
graph tests in `tests/test_relationships_api.py`. Nothing else uses them (checked 2026-10-03:
only `MapPage.tsx` and those tests).

## 6. Order of work

1. Map page rewrite (5.1-5.3), so the Changes "Explore on map" links have a target.
2. Changes list redesign (4.1).
3. Remove the graph endpoint and its tests (5.4). Run `tests/test_relationships_api.py`,
   `tests/test_api_read_model_boundary.py`, `tests/test_principal_ips_api_spelling.py`.
5. `cd frontend && npm run lint && npm run build && sh scripts/check-color-budget.sh`.
6. `./run_server.sh restart` (serves `frontend/dist` on `:31102`).
7. Browser check (Playwright, Chromium at `/opt/pw-browsers` or the repo's `.venv`), EN and VI,
   1440 px and 390 px, no page errors, no failed `/api` calls, no horizontal overflow:
   - `/changes`: every rail filter, type chip click, Where-changes-are filter, pager, sort, View details,
     Investigate, Explore on map (opens the right anchor); old-style URLs still apply their filters;
   - `/workspace/map`: list switch, search + Enter, user → service (scope chip appears) → API,
     breadcrumb back, "+N more" filtering, Unknown users anchor.
   - Also test with a mocked large estate (intercept `/api/v1/relationships*` with 240 services,
     1,500 APIs, 180 users) to confirm the screen never shows more than 10 rows per side.
8. Update AGENTS.md and STATE.md.

## 7. Done when

- `/workspace/map` shows at most 1 centre + 20 neighbour rows at any estate size, every entity is
  reachable through search or the list, and there is no "Other" node.
- `/changes` uses the concept C layout with every existing filter, count and link still working,
  and each episode can open the map on its anchor. The detail page is unchanged.
- All listed tests pass, lint/build/colour guard are clean, browser checks pass.

## 8. Known limits to keep in mind

- Live data has 15 services in one catalog group, so the Group option of "Where changes are" is
  hidden until the catalog is filled.
- Pod IPs (`10.244.x`) are classed as client IPs, so much "unknown user" traffic is
  service-to-service calls without credentials.
- 7-day windows have no previous-window history until about 2026-10-15; use 24 h for testing.
