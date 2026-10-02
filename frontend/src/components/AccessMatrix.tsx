import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { ErrorState, Loading, n } from "../components";
import { useI18n } from "../i18n";
import { ENTITY_COLOR, STATE_STYLE, asState, stateLabel, getStateStyle, getEntityColor, type AccessMatrixResponse } from "../accessEncoding";
import { EntityLink } from "./EntityLink";
import { StateLegend, relativeAge } from "./AccessFlow";

const CELL = 18;
const ROW_LABEL_W = 170;
const COL_LABEL_H = 132;
const PAGE_SIZES = [25, 50, 100];

function clip(text: string, max: number) {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

export function AccessMatrix({ service = "", services = [] }: { service?: string; services?: string[] }) {
  const { lang } = useI18n();
  const t = (en: string, vi?: string) => (lang === "vi" && vi ? vi : en);
  const navigate = useNavigate();
  const [scope, setScope] = useState(service);
  const [order, setOrder] = useState<"similarity" | "traffic">("similarity");
  const [basis, setBasis] = useState<"observed" | "baseline">("observed");
  const [pageSize, setPageSize] = useState(50);
  const [rowOffset, setRowOffset] = useState(0);
  const [colOffset, setColOffset] = useState(0);
  const [cursor, setCursor] = useState<{ row: number; col: number }>({ row: 0, col: 0 });

  const params = new URLSearchParams({
    view: "matrix", order, basis, row_offset: String(rowOffset), row_limit: String(pageSize),
    col_offset: String(colOffset), col_limit: String(pageSize),
  });
  if (scope) params.set("service", scope);
  const query = useQuery({
    queryKey: ["access-matrix", params.toString()],
    queryFn: ({ signal }) => api<AccessMatrixResponse>(`/api/v1/behavior/access?${params}`, { signal }),
    placeholderData: previous => previous,
    refetchInterval: 60000,
  });
  const data = query.data;

  const cellMap = useMemo(() => new Map((data?.cells || []).map(c => [`${c.row}:${c.col}`, c])), [data]);
  const maxWidth = useMemo(() => Math.max(1e-9, ...(data?.cells || []).map(c => c.width_tps)), [data]);
  const intensity = (w: number) => Math.log1p((w / maxWidth) * 100) / Math.log1p(100);

  const rows = data?.rows || [];
  const cols = data?.cols || [];
  const width = ROW_LABEL_W + cols.length * CELL + 8;
  const height = COL_LABEL_H + rows.length * CELL + 8;
  const cur = { row: Math.min(cursor.row, Math.max(0, rows.length - 1)), col: Math.min(cursor.col, Math.max(0, cols.length - 1)) };
  const activeCell = cellMap.get(`${cur.row}:${cur.col}`);
  const rowName = rows[cur.row]?.name;
  const colName = cols[cur.col]?.name;

  const reset = () => { setRowOffset(0); setColOffset(0); setCursor({ row: 0, col: 0 }); };
  const onKey = (event: React.KeyboardEvent) => {
    const moves: Record<string, [number, number]> = { ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1] };
    const move = moves[event.key];
    if (!move) return;
    event.preventDefault();
    setCursor({ row: Math.max(0, Math.min(rows.length - 1, cur.row + move[0])), col: Math.max(0, Math.min(cols.length - 1, cur.col + move[1])) });
  };

  return (
    <div data-testid="access-matrix" className="space-y-2">
      <div className="flex flex-wrap items-center gap-2 px-2 pt-2 text-xs">
        <label className="flex items-center gap-1 text-muted">
          Service
          <input list="access-matrix-services" className="toolbar-control h-8 w-44 px-2" value={scope} placeholder={t("All Services", "Tất cả Service")}
            aria-label={t("Limit to Service", "Giới hạn theo Service")}
            onChange={e => { setScope(e.target.value); reset(); }} />
          <datalist id="access-matrix-services">{services.slice(0, 500).map(s => <option key={s} value={s} />)}</datalist>
        </label>
        <div role="group" aria-label={t("Row order", "Thứ tự hàng")} className="inline-flex">
          {(["similarity", "traffic"] as const).map(value => (
            <button key={value} type="button" aria-pressed={order === value} onClick={() => { setOrder(value); reset(); }}
              className={`btn ${order === value ? "border-accent bg-accent-soft text-accent" : ""}`}>
              {value === "similarity" ? t("Group by similar access", "Nhóm theo quyền truy cập giống nhau") : t("By traffic", "Theo lưu lượng")}
            </button>
          ))}
        </div>
        <div role="group" aria-label={t("Intensity basis", "Cơ sở cường độ")} className="inline-flex">
          {(["observed", "baseline"] as const).map(value => (
            <button key={value} type="button" aria-pressed={basis === value} onClick={() => setBasis(value)}
              className={`btn ${basis === value ? "border-accent bg-accent-soft text-accent" : ""}`}>
              {value === "observed" ? t("Observed TPS", "TPS quan sát") : t("Learned baseline", "Baseline đã học")}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-1 text-muted">
          {t("Page size", "Cỡ trang")}
          <select className="btn" value={pageSize} onChange={e => { setPageSize(Number(e.target.value)); reset(); }}>
            {PAGE_SIZES.map(v => <option key={v} value={v}>{v}</option>)}
          </select>
        </label>
      </div>

      {query.isLoading ? <Loading /> : query.isError ? (
        <div className="px-2"><ErrorState message={(query.error as Error).message} /><button className="btn" onClick={() => query.refetch()}>{t("Retry", "Thử lại")}</button></div>
      ) : !data || data.status === "learning" || !rows.length ? (
        <div className="px-3 py-8 text-center text-xs text-muted">{t("No learned credential access to show yet. Anonymous traffic is never a credential row.", "Chưa có quyền truy cập credential đã học. Lưu lượng ẩn danh không bao giờ là hàng credential.")}</div>
      ) : (
        <>
          <div className="overflow-auto px-2" style={{ maxHeight: 620 }} data-testid="access-matrix-scroll">
            <svg role="grid" tabIndex={0} onKeyDown={onKey} width={width} height={height} viewBox={`0 0 ${width} ${height}`} className="block max-w-none outline-none focus-visible:outline focus-visible:outline-1 focus-visible:outline-accent"
              aria-label={t("Credential by API access matrix. Arrow keys move between cells.", "Ma trận truy cập credential theo API. Dùng phím mũi tên để di chuyển giữa các ô.")}>
              {cols.map((col, c) => (
                <text key={col.name} transform={`translate(${ROW_LABEL_W + c * CELL + CELL / 2 + 3},${COL_LABEL_H - 6}) rotate(-60)`} fontSize="10" fill={c === cur.col ? "var(--text)" : getEntityColor("api")}
                  fontFamily="ui-monospace, monospace" className="cursor-pointer" onClick={() => navigate(`/behavior?tab=flow&focus_type=api&focus=${encodeURIComponent(col.name)}`)}>
                  {clip(col.name, 24)}<title>{col.name}</title>
                </text>
              ))}
              {rows.map((row, r) => (
                <g key={row.name}>
                  <text x={ROW_LABEL_W - 6} y={COL_LABEL_H + r * CELL + CELL - 5} textAnchor="end" fontSize="10.5" fill={r === cur.row ? "var(--text)" : getEntityColor("credential")}
                    fontFamily="ui-monospace, monospace" className="cursor-pointer" onClick={() => navigate(`/behavior?tab=flow&focus_type=credential&focus=${encodeURIComponent(row.name)}`)}>
                    {clip(row.name, 24)}<title>{row.name}</title>
                  </text>
                  <line x1={ROW_LABEL_W} x2={width - 8} y1={COL_LABEL_H + (r + 1) * CELL} y2={COL_LABEL_H + (r + 1) * CELL} stroke="var(--grid)" strokeWidth="0.5" />
                </g>
              ))}
              {cols.map((col, c) => <line key={col.name} y1={COL_LABEL_H} y2={height - 8} x1={ROW_LABEL_W + (c + 1) * CELL} x2={ROW_LABEL_W + (c + 1) * CELL} stroke="var(--grid)" strokeWidth="0.5" />)}
              {(data.cells).map(cell => {
                const state = asState(cell.state);
                const style = getStateStyle(state);
                const flagged = state === "new" || state === "deviating";
                const opacity = state === "ghost" ? style.fillOpacity : flagged ? Math.max(0.55, intensity(cell.width_tps)) : Math.max(0.18, intensity(cell.width_tps)) * 0.9;
                const x = ROW_LABEL_W + cell.col * CELL + 1;
                const y = COL_LABEL_H + cell.row * CELL + 1;
                return (
                  <g key={`${cell.row}:${cell.col}`} data-testid="matrix-cell" data-state={cell.state} onMouseEnter={() => setCursor({ row: cell.row, col: cell.col })}
                    onClick={() => setCursor({ row: cell.row, col: cell.col })}>
                    <rect x={x} y={y} width={CELL - 2} height={CELL - 2} fill={style.color} fillOpacity={opacity}
                      stroke={style.color} strokeOpacity={style.strokeOpacity} strokeDasharray={style.dash} strokeWidth={flagged || state !== "established" ? 1.25 : 0} />
                    {style.glyph && <text x={x + (CELL - 2) / 2} y={y + 12} textAnchor="middle" fontSize="11" fontWeight="700" fill={flagged ? "var(--surface)" : style.color} aria-hidden="true">{style.glyph}</text>}
                  </g>
                );
              })}
              <rect x={ROW_LABEL_W + cur.col * CELL} y={COL_LABEL_H + cur.row * CELL} width={CELL} height={CELL} fill="none" stroke="var(--accent)" strokeWidth="1.5" pointerEvents="none" />
            </svg>
          </div>

          <div className="flex flex-wrap items-center gap-2 px-2 text-xs text-muted" data-testid="matrix-paging">
            <span>
              {t("Showing", "Hiển thị")} {t("credentials", "credential")} {data.row_offset + 1}–{data.row_offset + rows.length} {t("of", "trên")} {data.row_total} · {t("APIs", "API")} {data.col_offset + 1}–{data.col_offset + cols.length} {t("of", "trên")} {data.col_total}
            </span>
            <button className="btn" type="button" disabled={rowOffset === 0} onClick={() => setRowOffset(Math.max(0, rowOffset - pageSize))}>{t("Prev rows", "Hàng trước")}</button>
            <button className="btn" type="button" disabled={rowOffset + pageSize >= data.row_total} onClick={() => setRowOffset(rowOffset + pageSize)}>{t("Next rows", "Hàng sau")}</button>
            <button className="btn" type="button" disabled={colOffset === 0} onClick={() => setColOffset(Math.max(0, colOffset - pageSize))}>{t("Prev APIs", "API trước")}</button>
            <button className="btn" type="button" disabled={colOffset + pageSize >= data.col_total} onClick={() => setColOffset(colOffset + pageSize)}>{t("Next APIs", "API sau")}</button>
            {data.similarity_capped && <span className="text-warn">{t("Similarity ordering covers only the busiest 1,000; the rest follow by traffic.", "Sắp xếp tương tự chỉ áp dụng cho 1.000 mục bận nhất; phần còn lại theo lưu lượng.")}</span>}
          </div>

          <div className="mx-2 min-h-[80px] rounded-card border border-line bg-surface p-3 text-xs shadow-card" aria-live="polite" data-testid="matrix-readout">
            {rowName && colName ? (
              <>
                <div className="mb-1 flex flex-wrap items-center gap-2">
                  <span className="font-mono text-entity-user font-semibold">{rowName}</span><span aria-hidden="true">→</span><span className="break-all font-mono text-entity-api font-semibold">{colName}</span>
                  {activeCell ? (() => {
                    const state = asState(activeCell.state);
                    const style = getStateStyle(state);
                    return <span className="rounded-ctl px-1.5 py-0.5" style={{ background: `${style.color}26`, color: style.color }}>{style.glyph} {stateLabel(t, state)}</span>;
                  })() : <span className="text-muted">{t("no learned relationship", "không có quan hệ đã học")}</span>}
                </div>
                {activeCell && (
                  <dl className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-muted md:grid-cols-4">
                    <dt>{t("Observed TPS", "TPS quan sát")}</dt><dd className="font-mono text-ink">{n(activeCell.observed_tps, 4)}</dd>
                    <dt>{t("Expected TPS", "TPS kỳ vọng")}</dt><dd className="font-mono text-ink">{activeCell.expected_tps != null ? n(activeCell.expected_tps, 4) : "—"}</dd>
                    <dt>{t("Familiarity", "Độ quen thuộc")}</dt><dd className="text-ink">{activeCell.familiarity}</dd>
                    <dt>{t("Last seen", "Lần cuối")}</dt><dd className="text-ink">{relativeAge(activeCell.last_seen_ms, data.as_of_ms, t)}</dd>
                  </dl>
                )}
                <div className="mt-1 flex flex-wrap gap-3">
                  <EntityLink entity={{ kind: "user", principal: rowName }}>{t("Open credential activity", "Mở hoạt động credential")}</EntityLink>
                  {colName.includes(" → ") && (() => { const [svc, op] = colName.split(" → "); return <EntityLink entity={{ kind: "api", service: svc, operation: op }}>{t("Open API", "Mở API")}</EntityLink>; })()}
                </div>
              </>
            ) : null}
          </div>
          <div className="px-2 pb-2"><StateLegend /></div>
        </>
      )}
    </div>
  );
}
