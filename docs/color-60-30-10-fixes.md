# 60/30/10 Follow-up Fixes (frontend/)

Status: done (2026-10-02). Follow-up to `docs/color-60-30-10-plan.md` (implemented) after review.
Audience: an implementing agent. Same ground rules as the plan §0: xHatsu line first, `frontend/` only, POSIX `sh`, no `kubectl`, no `git checkout/stash/reset`, edit only needed lines, no layout/copy changes, no commit.

## Already done (do not redo)

Unused files were removed on 2026-10-02 (unreachable from `src/main.tsx`; routes `/anomalies*`, `/accounts*`, `/principals*` are redirects in `App.tsx`; `/topology` renders `InteractiveTopology`):
`src/components/AccessBoardColumn.tsx`, `src/pages/Accounts.tsx`, `src/pages/Anomalies.tsx`, `src/pages/Principals.tsx`, `src/pages/Topology.tsx`, `src/pages/UserIntelligence.tsx`.
They are deleted in the working tree (unstaged); HEAD still has the old versions. `npm run build` and the color guard pass after removal. This also resolved review issues "hard-coded violet heatmap" (`UserIntelligence.tsx:151`) and most invisible `text-white` text. **Do not recreate these files**; if any is needed again, restore it from git and route it in `App.tsx` first.

Remaining work, in order. Each fix ends with its own check.

---

## Fix 1 — Contrast on the structure tier (WCAG AA ≥ 4.5:1)

Measured (light / dark):

| Pair | Light | Dark |
|---|---|---|
| `--muted` on `--structure` | **4.24 ❌** | 7.12 |
| `--muted` on `--structure-2` (hover) | **3.87 ❌** | — |
| `--faint` on `--structure` | **2.25 ❌** | **3.78 ❌** |

Where it shows: sidebar group labels (`App.tsx:145`, `text-muted`), table header text (`.table-head` in `index.css`, `color: var(--muted)` on `--structure`), toolbar status text (`App.tsx:386, 407, 455, 496`), filter hint (`App.tsx:512`, `text-faint`).

Steps:
1. `src/styles/tokens.css`, light `:root` block: `--muted: #71717a;` → `--muted: #65656d;` (5.07 on structure, 4.63 on structure-2, 5.78 on white).
2. Same file, light block: `--faint: #a1a1aa;` → `--faint: #8b8b94;` (keeps faint visibly lighter than muted; it is decorative-only after step 4).
3. Dark block: `--faint: #71717a;` → `--faint: #80808a;` (4.67 on structure, 4.53 on surface). Leave dark `--muted`.
4. `src/App.tsx:512` filter hint: `text-faint` → `text-muted` (it is informative text). Leave `text-faint` on the search icon / placeholder (lines 393, 399): those are on `bg-bg` and decorative.
5. Rule going forward: on `--structure` backgrounds, readable text is `text-ink`, `text-structure-ink` or `text-muted`; never `text-faint`.

Check:
```sh
cd /home/ubuntu/Viettel/OtelTrace/frontend
python3 - <<'EOF'
import re
css=open('src/styles/tokens.css').read(); light,dark=css.split(':root[data-theme="dark"]')
tok=lambda b: dict(re.findall(r'--([\w-]+):\s*(#[0-9a-fA-F]{6})',b))
def L(h):
    c=[int(h[i:i+2],16)/255 for i in (1,3,5)]; c=[x/12.92 if x<=.03928 else ((x+.055)/1.055)**2.4 for x in c]
    return .2126*c[0]+.7152*c[1]+.0722*c[2]
cr=lambda a,b:(max(L(a),L(b))+.05)/(min(L(a),L(b))+.05)
bad=0
for n,b in (('light',light),('dark',dark)):
    t=tok(b)
    for fg,bg,need in [('structure-text','structure',4.5),('text','structure',4.5),('muted','structure',4.5),
                       ('muted','structure-2',4.5),('muted','surface',4.5),('accent','structure',3.0),('text','accent-soft',4.5)]:
        r=cr(t[fg],t[bg]); ok=r>=need; bad+=not ok
        print(f"{'ok ' if ok else 'BAD'} {n:5} {fg} on {bg}: {r:.2f} (need {need})")
raise SystemExit(bad)
EOF
```
Must exit 0. (`accent` on structure needs 3.0: it is used for icons/indicator bars, not body text.)

---

## Fix 2 — Text and lines that only work in dark mode

These are hard-coded white/black values that disappear (white on white) or look heavy in light mode. Replace them with tokens. No visual change in dark mode is intended.

| Find | Replace with |
|---|---|
| `text-white` on a neutral surface (not on `bg-accent`/`bg-bad`/`bg-good`/`bg-warn`/`bg-info`/entity fill) | `text-ink` |
| `text-white/NN` | `text-muted` |
| `border-[rgba(255,255,255,0.04..0.06)]`, `border-white/5`, `border-white/[0.06]` | `border-line` |
| `border-[rgba(255,255,255,0.18)]` | `border-line-strong` |
| `divide-[rgba(255,255,255,0.04)]`, `divide-white/5`, `divide-white/10` | `divide-line` (if Tailwind has no `divide-line`, use `divide-[color:var(--border)]`, it is a token reference, not a raw color) |
| `bg-white/[0.01..0.06]` (row/panel tint) | `bg-surface-2` (header/stripe) or `hover:bg-hover` (hover state) |
| `bg-black/30..40` (inset blocks, code boxes) | `bg-surface-2` |
| `bg-black/80` | keep only if it is a modal/overlay backdrop; otherwise `bg-surface-2` |
| `text-black` | `text-ink` (or keep if it sits on a fixed light fill like `bg-warn` — check) |

Exact locations (2026-10-02):

- `src/pages/UnknownUsers.tsx`: `text-white` at lines 134, 213, 293, 307, 336, 350, 375, 422, 468 (input text), 507, 512 → `text-ink`; `border-white/5` at 211, 292, 335, 374, 420 → `border-line`; `divide-white/5` at 489 → `divide-line`; `text-black` at 453 → check background, usually `text-ink`.
- `src/pages/Traces.tsx`: 133 `border-[rgba(255,255,255,0.06)] bg-white/[0.01]` → `border-line bg-surface-2`; 143 `divide-[rgba(…0.04)]` → `divide-line`; 150 `bg-white/[0.03]` → `bg-hover`; 432 `bg-black/40 … border-[rgba(…0.06)]` → `bg-surface-2 … border-line`.
- `src/pages/Services.tsx`: 814 `divide-[rgba(…0.04)]` → `divide-line`; 818 `bg-white/[0.02]` → `bg-hover`.
- `src/pages/user/UserDirectory.tsx`: 133, 184 `border-[rgba(…0.18)]` → `border-line-strong`; 117, 123 `bg-black/30` and 141, 147 `bg-black/40` → `bg-surface-2`; 201 `divide-white/10` → `divide-line`; 224 `bg-white/[0.06]` → `bg-hover`.
- `src/pages/AgentStats.tsx`: 238, 1168, 1187 `border-[rgba(…)]` → `border-line`; 1127–1147 (5×) `border-r border-[rgba(…0.06)]` → `border-r border-line`; 275 `border-white/[0.06]` → `border-line`; 508, 1238 `bg-black/80` → inspect: keep if overlay backdrop.

Line numbers drift after the first edit in a file; re-locate with:
```sh
grep -nE 'text-white|text-black|(bg|border|divide)-(white|black)|rgba\(255,255,255' src/pages/UnknownUsers.tsx
```

Check (expected after fix):
```sh
grep -rnoE 'rgba\(255,255,255' src | wc -l                                  # 0
grep -rnoE '\b(border|divide)-(white|black)' src | wc -l                    # 0
grep -rnoE '\bbg-white/' src | wc -l                                        # 0
grep -rnoE 'className="[^"]*text-white[^"]*"' src | grep -vE 'bg-(accent|bad|good|warn|info|entity)' | wc -l   # 0, or only verified colored fills
```
Then open `/unknown-users`, `/traces`, `/users`, `/agent-stats`, `/services/order-service` in **light** mode: every heading, table cell and input text readable; dividers visible but faint.

---

## Fix 3 — Raw accent RGBA in `theme.tsx`

`src/theme.tsx` lines ~196–197 and ~255–256 hard-code `rgba(109, 74, 232, …)` (the light accent) as chart area fallbacks. In dark mode the fallback is the wrong violet.

- Computed branch: keep `readCssVar("--chart-area-top", …)` but make the fallback `"var(--chart-area-top)"` (same for bottom).
- Static fallback object: `areaTop: "var(--chart-area-top)"`, `areaBottom: "var(--chart-area-bottom)"`.

Check: `grep -n "rgba(109" src/theme.tsx` → nothing.

---

## Fix 4 — Extend the guard so these cannot come back

Append to `frontend/scripts/check-color-budget.sh`, before `exit $fail`:

```sh
check "white rgba literals"         'rgba\(255, ?255, ?255'                  0
check "raw rgba in ts/tsx"          'rgba\([0-9]'                             0
check "white/black borders+dividers" '\b(border|divide)-(white|black)'       0
check "bg-white tints"              '\bbg-white/'                             0
check "faint on structure (App)"    'text-faint">\{hint'                      0
```

Notes:
- `count()` also scans `.css`; `tokens.css` contains `rgba(` values on purpose. Change the `raw rgba` check to only `.ts/.tsx`: add a second helper

```sh
count_ts() {
  grep -rhoE "$1" src --include=*.ts --include=*.tsx 2>/dev/null | wc -l | tr -d ' '
}
```
and make that check call `count_ts` (copy `check` to `check_ts` using `count_ts`). Keep POSIX: no `local`, no arrays.
- The last check is a narrow regression guard for Fix 1 step 4; delete it if `App.tsx` is restructured.

Check: `sh scripts/check-color-budget.sh` exits 0.

---

## Fix 5 — Out-of-date page tests

`backend/scripts/test_pages_playwright.py` fails 3 cases that test removed UI (not caused by the color work):
- `/topology`: waits for `[data-testid='topology-time-slider']` — the slider was removed when topology moved to learned data (2026-09-29). Replace with a wait for the canvas/service cards (e.g. a node card selector used in `InteractiveTopology.tsx`), or drop the slider assertions.
- `/users/david_wsse/overview` and `/users/david_wsse/activity`: expect a Behavior | Access segmented control — removed in the User detail redesign (2026-10-02). Assert instead that the page shows the KPI cards and the `Access for {user}` section.

This file is under `backend/scripts/` (test tooling, no runtime effect); editing it is allowed for this fix only.

Check: `.venv/bin/python backend/scripts/test_pages_playwright.py` → all PASS, 0 JS errors.

---

## Fix 6 — Records

1. `AGENTS.md` section "60/30/10 Color Architecture Plan … COMPLETE":
   - Phase 5 pixel shares: replace "pass" wording with the measured truth: 6/8 routes in target; `/changes` (base 76–77 %, structure 20–22 %) and `/topology` (base 75–77 %, structure 20–23 %) are content-driven exceptions (empty triage list / open graph canvas); dark `/services` base 68.2 % borderline.
   - Contrast line: replace "10.5:1 / 11.6:1" with the Fix 1 table results after the fix.
   - Add: unused files removed (list above), Fixes 1–5 done.
2. `STATE.md`: delete the stale block `## 60/30/10 color plan (2026-10-02)` ("Plan only … Not implemented", near the end of the file) and mirror the AGENTS.md update.
3. `docs/color-60-30-10-plan.md` line 3: `Status: ready to execute … Not started.` → `Status: implemented 2026-10-02; follow-ups in docs/color-60-30-10-fixes.md.`
4. This file: change `Status: open` → `Status: done (date)`.

---

## Final verification

```sh
cd /home/ubuntu/Viettel/OtelTrace/frontend
npm run lint && npm run build && sh scripts/check-color-budget.sh
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:31102/          # 200 (dist is served directly)
cd .. && .venv/bin/python backend/scripts/test_pages_playwright.py         # all PASS
```
Re-run the pixel-share script from `docs/color-60-30-10-plan.md` §7.1 and paste the new table into AGENTS.md. Light `--muted` changes text only, so tier shares should move < 0.5 pt.

## Effort
Fix 1: 20 min · Fix 2: 45 min · Fix 3: 5 min · Fix 4: 15 min · Fix 5: 30 min · Fix 6: 15 min → about 2 h 15 min.
