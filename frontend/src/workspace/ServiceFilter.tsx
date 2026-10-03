import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { Check, ChevronDown, Search, X } from "lucide-react";
import { n } from "../components";
import { useI18n } from "../i18n";
import type { FacetResult, MetaKey, MetaOption, MultiFacet, RelRow, SelectionApi } from "./model";

// Service filter built for estates with hundreds of services: catalog levels
// (environment → group → module) narrow the list, then a searchable multi-select
// picks individual services. Callers are services too and reuse the same picker.

type GroupBy = MetaKey | "none";
const META_ORDER: MetaKey[] = ["environment", "group", "module"];

function useMetaLabels() {
  const { t, lang } = useI18n();
  return {
    environment: t("Environment", "Môi trường"),
    // "Group" alone hits a shared dictionary entry that keeps it in English.
    group: lang === "vi" ? "Nhóm" : "Group",
    module: t("Module", "Module"),
  } as Record<MetaKey, string>;
}

export function ServiceFilterBar({ facet = "service", result, options, sel, label, showMeta = true, showPicker = true }: {
  facet?: MultiFacet;
  showPicker?: boolean;
  result?: FacetResult;
  options?: Record<MetaKey, MetaOption[]>;
  sel: SelectionApi;
  label: string;
  showMeta?: boolean;
}) {
  const { t } = useI18n();
  const metaLabels = useMetaLabels();
  const selected = sel.selection[facet] || [];
  const levels = showMeta ? META_ORDER.filter((key) => (options?.[key]?.length || 0) > 1 || sel.selection[key]) : [];
  if (!showPicker && !levels.length) return null;
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-card border border-line bg-surface px-2.5 py-2 text-xs">
      {levels.map((key) => (
        <label key={key} className="flex items-center gap-1.5">
          <span className="text-[11px] text-muted">{metaLabels[key]}</span>
          <select
            value={sel.selection[key] || ""}
            onChange={(event) => sel.setMeta(key, event.target.value)}
            className="max-w-[11rem] rounded-ctl border border-line-strong bg-surface-2 px-2 py-1 text-xs text-ink"
          >
            <option value="">{t("All", "Tất cả")}</option>
            {(options?.[key] || []).map((option) => <option key={option.value} value={option.value}>{option.value} ({option.services})</option>)}
          </select>
        </label>
      ))}
      {showPicker && <ServicePicker
        label={label}
        rows={result?.items || []}
        total={result?.total || 0}
        selected={selected}
        onChange={(values) => sel.setMany(facet, values)}
        groupable={META_ORDER.filter((key) => (options?.[key]?.length || 0) > 1)}
      />}
      {selected.slice(0, 3).map((value) => (
        <span key={value} className="inline-flex max-w-[14rem] items-center gap-1 rounded-ctl border border-line-strong px-1.5 py-0.5 font-mono text-entity-service">
          <span className="truncate" title={value}>{value}</span>
          <button type="button" aria-label={`${t("Remove", "Bỏ")} ${value}`} onClick={() => sel.remove(facet, value)} className="text-muted hover:text-ink"><X size={11} /></button>
        </span>
      ))}
      {selected.length > 3 && <span className="text-[11px] text-muted">+{selected.length - 3}</span>}
      {(selected.length > 0 || levels.some((key) => sel.selection[key])) && (
        <button type="button" onClick={() => (showMeta ? sel.reset(facet) : sel.setMany(facet, []))} className="ml-auto text-[11px] text-muted hover:text-ink hover:underline">
          {t("Reset", "Đặt lại")}
        </button>
      )}
    </div>
  );
}

type Item = { row: RelRow; selected: boolean };
type Section = { key: string; label: string; items: Item[]; requests: number };

export function ServicePicker({ label, rows, total, selected, onChange, groupable }: {
  label: string;
  rows: RelRow[];
  total: number;
  selected: string[];
  onChange: (values: string[]) => void;
  groupable: MetaKey[];
}) {
  const { t } = useI18n();
  const metaLabels = useMetaLabels();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  // Until the operator picks a grouping, follow the data: Group when services span several groups.
  const [chosenGroupBy, setGroupBy] = useState<GroupBy | null>(null);
  const groupBy: GroupBy = chosenGroupBy && (chosenGroupBy === "none" || groupable.includes(chosenGroupBy))
    ? chosenGroupBy
    : groupable.includes("group") ? "group" : groupable[0] || "none";
  const [active, setActive] = useState(0);
  const root = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const list = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => { if (!root.current?.contains(event.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", close);
    input.current?.focus();
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  const maxRequests = Math.max(1, ...rows.map((row) => row.requests));
  const { sections, flat, matches } = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const chosen = new Set(selected);
    const matching = rows.filter((row) => !needle || [row.name, row.group, row.module, row.environment].some((value) => value?.toLowerCase().includes(needle)));
    const out: Section[] = [];
    // Selected services stay on top, even when they no longer match the search.
    const pinned = selected.map((name) => rows.find((row) => row.name === name) || ({ name, requests: 0, state: "silent" } as RelRow));
    if (pinned.length) out.push({ key: "__selected", label: t("Selected", "Đã chọn"), items: pinned.map((row) => ({ row, selected: true })), requests: 0 });
    const rest = matching.filter((row) => !chosen.has(row.name));
    if (groupBy === "none") {
      if (rest.length) out.push({ key: "__all", label: needle ? t("Matches", "Kết quả") : t("By traffic", "Theo lưu lượng"), items: rest.map((row) => ({ row, selected: false })), requests: 0 });
    } else {
      const groups = new Map<string, Section>();
      rest.forEach((row) => {
        const key = row[groupBy] || "—";
        const section = groups.get(key) || { key, label: key, items: [], requests: 0 };
        section.items.push({ row, selected: false });
        section.requests += row.requests;
        groups.set(key, section);
      });
      out.push(...[...groups.values()].sort((a, b) => b.requests - a.requests || a.label.localeCompare(b.label)));
    }
    return { sections: out, flat: out.flatMap((section) => section.items), matches: matching.length };
  }, [rows, query, selected, groupBy, t]);

  const toggle = (name: string) => onChange(selected.includes(name) ? selected.filter((value) => value !== name) : [...selected, name]);
  const onKey = (event: KeyboardEvent) => {
    if (event.key === "Escape") { setOpen(false); return; }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const next = Math.max(0, Math.min(flat.length - 1, active + (event.key === "ArrowDown" ? 1 : -1)));
      setActive(next);
      list.current?.querySelector(`[data-index="${next}"]`)?.scrollIntoView({ block: "nearest" });
    }
    if (event.key === "Enter" && flat[active]) { event.preventDefault(); toggle(flat[active].row.name); }
  };

  const summary = selected.length === 0 ? t(`All (${n(total, 0)})`, `Tất cả (${n(total, 0)})`)
    : selected.length === 1 ? selected[0] : t(`${selected.length} selected`, `Đã chọn ${selected.length}`);
  let index = -1;
  return (
    <div ref={root} className="relative" onKeyDown={onKey}>
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className={`inline-flex max-w-[18rem] items-center gap-1.5 rounded-ctl border px-2 py-1 ${selected.length ? "border-line-strong bg-accent-soft text-ink" : "border-line-strong bg-surface-2 text-ink"}`}
      >
        <span className="text-[11px] text-muted">{label}</span>
        <span className="truncate font-mono font-semibold">{summary}</span>
        <ChevronDown size={12} className="shrink-0 text-muted" />
      </button>
      {open && (
        <div className="absolute left-0 top-full z-40 mt-1 flex w-[min(28rem,calc(100vw-2.5rem))] flex-col rounded-card border border-line-strong bg-surface shadow-card">
          <div className="flex items-center gap-2 border-b border-line px-2.5 py-2">
            <Search size={13} className="text-muted" />
            <input
              ref={input}
              value={query}
              onChange={(event) => { setQuery(event.target.value); setActive(0); }}
              placeholder={t("Search name, group, module…", "Tìm tên, nhóm, module…")}
              aria-label={`${t("Search", "Tìm")} ${label}`}
              className="min-w-0 flex-1 bg-transparent text-xs text-ink outline-none placeholder:text-faint"
            />
            <span className="shrink-0 font-mono text-[10px] text-muted">{n(matches, 0)} / {n(total, 0)}</span>
          </div>
          {groupable.length > 0 && (
            <div className="flex items-center gap-1 border-b border-line px-2.5 py-1.5 text-[11px]" role="group" aria-label={t("Group by", "Nhóm theo")}>
              <span className="mr-1 text-muted">{t("Group by", "Nhóm theo")}</span>
              {[...groupable, "none" as const].map((key) => (
                <button key={key} type="button" aria-pressed={groupBy === key} onClick={() => setGroupBy(key)}
                  className={`rounded-ctl px-1.5 py-0.5 ${groupBy === key ? "bg-accent-soft font-semibold text-ink" : "text-muted hover:text-ink"}`}>
                  {key === "none" ? t("None", "Không") : metaLabels[key]}
                </button>
              ))}
            </div>
          )}
          <div ref={list} role="listbox" aria-multiselectable="true" className="max-h-[min(24rem,60vh)] overflow-y-auto py-1">
            {sections.map((section) => {
              const unselected = section.items.filter((item) => !item.selected).map((item) => item.row.name);
              return (
                <div key={section.key}>
                  <div className="sticky top-0 z-[1] flex items-center gap-2 bg-surface-2 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider text-muted">
                    <span className="truncate">{section.label}</span>
                    <span className="font-mono">{section.items.length}</span>
                    {unselected.length > 1 && (
                      <button type="button" onClick={() => onChange([...selected, ...unselected].slice(0, 500))} className="ml-auto normal-case tracking-normal hover:text-ink hover:underline">
                        {t("Select all", "Chọn tất cả")}
                      </button>
                    )}
                  </div>
                  {section.items.map((item) => {
                    index += 1;
                    const at = index;
                    const row = item.row;
                    return (
                      <div
                        key={`${section.key}|${row.name}`}
                        role="option"
                        aria-selected={item.selected}
                        data-index={at}
                        onMouseEnter={() => setActive(at)}
                        onClick={() => toggle(row.name)}
                        className={`group flex cursor-pointer items-center gap-2 px-2.5 py-1 text-xs ${at === active ? "bg-hover" : ""}`}
                      >
                        <span className={`flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-[2px] border ${item.selected ? "border-line-strong bg-accent-soft text-ink" : "border-line-strong"}`}>
                          {item.selected && <Check size={10} />}
                        </span>
                        <span className={`min-w-0 flex-1 truncate font-mono ${row.requests ? "text-entity-service" : "text-muted"}`} title={row.name}>{row.name}</span>
                        {groupBy !== "module" && row.module && groupable.includes("module") && <span className="hidden shrink-0 truncate text-[10px] text-faint sm:inline">{row.module}</span>}
                        <span className="h-1 w-12 shrink-0 overflow-hidden rounded-full bg-surface-2" aria-hidden>
                          <span className="block h-full bg-accent" style={{ width: `${Math.max(2, (row.requests / maxRequests) * 100)}%` }} />
                        </span>
                        <span className="w-14 shrink-0 text-right font-mono text-[10px] tabular-nums text-muted">{row.requests ? n(row.requests, 0) : t("silent", "im lặng")}</span>
                        <button type="button" onClick={(event) => { event.stopPropagation(); onChange([row.name]); }}
                          className="shrink-0 text-[10px] text-muted opacity-0 hover:text-ink hover:underline focus:opacity-100 group-hover:opacity-100">
                          {t("only", "chỉ")}
                        </button>
                      </div>
                    );
                  })}
                </div>
              );
            })}
            {!flat.length && <p className="px-3 py-4 text-center text-xs text-muted">{t("No service matches", "Không có service phù hợp")}</p>}
          </div>
          <div className="flex items-center gap-2 border-t border-line px-2.5 py-1.5 text-[11px] text-muted">
            <span>{selected.length ? t(`${selected.length} selected`, `Đã chọn ${selected.length}`) : t("Showing all", "Đang hiện tất cả")}</span>
            {total > rows.length && <span className="text-faint">· {t(`only the busiest ${rows.length} are listed`, `chỉ liệt kê ${rows.length} service nhiều nhất`)}</span>}
            {selected.length > 0 && <button type="button" onClick={() => onChange([])} className="ml-auto hover:text-ink hover:underline">{t("Clear", "Bỏ chọn")}</button>}
            <button type="button" onClick={() => setOpen(false)} className={`${selected.length ? "" : "ml-auto"} font-semibold text-ink hover:underline`}>{t("Done", "Xong")}</button>
          </div>
        </div>
      )}
    </div>
  );
}
