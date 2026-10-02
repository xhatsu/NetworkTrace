#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";

// Neutral token mapping per docs/frontend-restyle-plan.md §2E Step 1
const BG_PAGE_HEX = [
  "#0b0c0e", "#0c0d14", "#0d0e12", "#0e0f12", "#0b0914", "#0c0e17", "#0e1116", "#12101b",
  "#f3f4f8", "#f3f6fa", "#0c0c0e", "#f7f7f8"
];
const BG_SURFACE_HEX = [
  "#111217", "#141622", "#141624", "#161424", "#161826", "#16181f", "#18181b",
  "#12151a", "#10121e", "#101219", "#0e1019", "#161825", "#161726", "#10121a", "#1e1938",
  "#ffffff", "#fff"
];
const BG_SURFACE_2_HEX = [
  "#181b1f", "#1a172a", "#202333", "#202226", "#1f222b", "#171329", "#181a28", "#10121c", "#0f111b",
  "#252934", "#1a1d2e", "#202436", "#292133", "#1e1e22",
  "#f1f3f5", "#f0f3f6", "#f1f5f9", "#f5f3fa", "#f8fafc", "#fafafa"
];

const BORDER_LINE_HEX = [
  "#2a2d30", "#262838", "#262a33", "#303449", "#2d3145", "#2d2644", "#2a2a30", "#2e3247",
  "#d5dee9", "#e2e8f0", "#cbd5e1", "#e8e8ec"
];
const BORDER_LINE_STRONG_HEX = [
  "#34373b", "#343947", "#34384c", "#3b3258", "#36363d", "#dcdce2", "#c9cdd7"
];

const TEXT_INK_HEX = [
  "#f1f3f5", "#f4f5f8", "#d8d9da", "#c9d1d9", "#172235", "#1f2330", "#f5f3fa", "#f4f4f5", "#18181b", "#f0f3f6"
];
const TEXT_MUTED_HEX = [
  "#a7a9ab", "#c2c6cc", "#8b949e", "#9ca3af", "#7b7d80", "#6e7681", "#9e96b8", "#c4bdd9",
  "#475569", "#64748b", "#71717a", "#a1a1aa", "#766e92", "#303236", "#c9c1d1", "#94a3b8"
];
const TEXT_FAINT_HEX = [
  "#59616b", "#5f6573", "#94a3b8", "#6e7681"
];

const GOOD_HEX = ["#73bf69", "#16a34a", "#22c55e", "#10b981", "#34d399"];
const BAD_HEX = ["#f2495c", "#dc2626", "#fb7185", "#ef4444", "#f43f5e"];
const WARN_HEX = ["#ff9830", "#d97706", "#f59e0b", "#f97316", "#ffb767", "#ffb45e"];
const INFO_HEX = ["#5794f2", "#1d63dc", "#3b82f6", "#2563eb", "#6b9cf5"];

function normalizeHex(h) {
  return h.toLowerCase();
}

const HEX_MAP = new Map();

for (const h of BG_PAGE_HEX) {
  HEX_MAP.set(`bg-[${normalizeHex(h)}]`, "bg-page");
}
for (const h of BG_SURFACE_HEX) {
  HEX_MAP.set(`bg-[${normalizeHex(h)}]`, "bg-surface");
}
HEX_MAP.set("bg-white", "bg-surface");

for (const h of BG_SURFACE_2_HEX) {
  HEX_MAP.set(`bg-[${normalizeHex(h)}]`, "bg-surface-2");
}

for (const h of BORDER_LINE_HEX) {
  HEX_MAP.set(`border-[${normalizeHex(h)}]`, "border-line");
  HEX_MAP.set(`border-t-[${normalizeHex(h)}]`, "border-t-line");
  HEX_MAP.set(`border-b-[${normalizeHex(h)}]`, "border-b-line");
  HEX_MAP.set(`border-l-[${normalizeHex(h)}]`, "border-l-line");
  HEX_MAP.set(`border-r-[${normalizeHex(h)}]`, "border-r-line");
}

for (const h of BORDER_LINE_STRONG_HEX) {
  HEX_MAP.set(`border-[${normalizeHex(h)}]`, "border-line-strong");
  HEX_MAP.set(`border-t-[${normalizeHex(h)}]`, "border-t-line-strong");
  HEX_MAP.set(`border-b-[${normalizeHex(h)}]`, "border-b-line-strong");
  HEX_MAP.set(`border-l-[${normalizeHex(h)}]`, "border-l-line-strong");
  HEX_MAP.set(`border-r-[${normalizeHex(h)}]`, "border-r-line-strong");
}

for (const h of TEXT_INK_HEX) {
  HEX_MAP.set(`text-[${normalizeHex(h)}]`, "text-ink");
}
for (const h of TEXT_MUTED_HEX) {
  HEX_MAP.set(`text-[${normalizeHex(h)}]`, "text-muted");
  HEX_MAP.set(`placeholder:text-[${normalizeHex(h)}]`, "placeholder:text-muted");
  HEX_MAP.set(`placeholder-[${normalizeHex(h)}]`, "placeholder:text-muted");
}
for (const h of TEXT_FAINT_HEX) {
  HEX_MAP.set(`text-[${normalizeHex(h)}]`, "text-faint");
}

for (const h of GOOD_HEX) {
  HEX_MAP.set(`text-[${normalizeHex(h)}]`, "text-good");
  HEX_MAP.set(`bg-[${normalizeHex(h)}]`, "bg-good-bg");
  HEX_MAP.set(`border-[${normalizeHex(h)}]`, "border-good");
}

for (const h of BAD_HEX) {
  HEX_MAP.set(`text-[${normalizeHex(h)}]`, "text-bad");
  HEX_MAP.set(`bg-[${normalizeHex(h)}]`, "bg-bad-bg");
  HEX_MAP.set(`border-[${normalizeHex(h)}]`, "border-bad");
}

for (const h of WARN_HEX) {
  HEX_MAP.set(`text-[${normalizeHex(h)}]`, "text-warn");
  HEX_MAP.set(`bg-[${normalizeHex(h)}]`, "bg-warn-bg");
  HEX_MAP.set(`border-[${normalizeHex(h)}]`, "border-warn");
}

for (const h of INFO_HEX) {
  HEX_MAP.set(`text-[${normalizeHex(h)}]`, "text-accent");
}

HEX_MAP.set("bg-[#34373b]", "bg-surface-2");
HEX_MAP.set("bg-[#7b7d80]", "bg-muted");
HEX_MAP.set("bg-[#73bf69]", "bg-good");
HEX_MAP.set("border-[#73bf69]/50", "border-good/50");
HEX_MAP.set("bg-[#73bf69]/10", "bg-good/10");
HEX_MAP.set("border-[#7b7d80]/50", "border-line");
HEX_MAP.set("bg-[#303236]", "bg-grid");
HEX_MAP.set("bg-[#2a2d30]", "bg-line");
HEX_MAP.set("border-[#303236]", "border-grid");
HEX_MAP.set("divide-[#303236]", "divide-grid");
HEX_MAP.set("divide-[#2a2d30]", "divide-line");
HEX_MAP.set("divide-[#303449]", "divide-line");
HEX_MAP.set("divide-[#d5dee9]", "divide-line");
HEX_MAP.set("divide-[#e2e8f0]", "divide-line");
HEX_MAP.set("divide-[#262838]", "divide-line");

// Slate / gray / zinc palette classes per §2E
const NEUTRALS = ["slate", "gray", "zinc", "neutral"];
for (const n of NEUTRALS) {
  HEX_MAP.set(`bg-${n}-50`, "bg-surface-2");
  HEX_MAP.set(`bg-${n}-100`, "bg-surface-2");
  HEX_MAP.set(`bg-${n}-200`, "bg-surface-2");
  HEX_MAP.set(`bg-${n}-800`, "bg-surface-2");
  HEX_MAP.set(`bg-${n}-900`, "bg-surface");
  HEX_MAP.set(`border-${n}-100`, "border-line");
  HEX_MAP.set(`border-${n}-200`, "border-line");
  HEX_MAP.set(`border-${n}-300`, "border-line");
  HEX_MAP.set(`border-${n}-700`, "border-line");
  HEX_MAP.set(`border-${n}-800`, "border-line");
  HEX_MAP.set(`text-${n}-300`, "text-muted");
  HEX_MAP.set(`text-${n}-400`, "text-muted");
  HEX_MAP.set(`text-${n}-500`, "text-muted");
  HEX_MAP.set(`text-${n}-600`, "text-faint");
  HEX_MAP.set(`text-${n}-700`, "text-ink");
  HEX_MAP.set(`text-${n}-800`, "text-ink");
  HEX_MAP.set(`text-${n}-900`, "text-ink");
  HEX_MAP.set(`hover:bg-${n}-50`, "hover:bg-hover");
  HEX_MAP.set(`hover:bg-${n}-100`, "hover:bg-hover");
  HEX_MAP.set(`hover:bg-${n}-200`, "hover:bg-hover");
  HEX_MAP.set(`hover:bg-${n}-800`, "hover:bg-hover");
  HEX_MAP.set(`hover:bg-${n}-900`, "hover:bg-hover");
  HEX_MAP.set(`hover:text-${n}-100`, "hover:text-ink");
  HEX_MAP.set(`hover:text-${n}-200`, "hover:text-ink");
  HEX_MAP.set(`hover:text-${n}-900`, "hover:text-ink");
}

// Emerald / green -> good
for (const c of ["emerald", "green"]) {
  HEX_MAP.set(`text-${c}-300`, "text-good");
  HEX_MAP.set(`text-${c}-400`, "text-good");
  HEX_MAP.set(`text-${c}-500`, "text-good");
  HEX_MAP.set(`text-${c}-600`, "text-good");
  HEX_MAP.set(`bg-${c}-500`, "bg-good");
  HEX_MAP.set(`bg-${c}-600`, "bg-good");
  HEX_MAP.set(`border-${c}-500`, "border-good");
  HEX_MAP.set(`border-${c}-400`, "border-good");
}

// Rose / red -> bad
for (const c of ["rose", "red"]) {
  HEX_MAP.set(`text-${c}-300`, "text-bad");
  HEX_MAP.set(`text-${c}-400`, "text-bad");
  HEX_MAP.set(`text-${c}-500`, "text-bad");
  HEX_MAP.set(`text-${c}-600`, "text-bad");
  HEX_MAP.set(`bg-${c}-500`, "bg-bad");
  HEX_MAP.set(`bg-${c}-600`, "bg-bad");
  HEX_MAP.set(`border-${c}-500`, "border-bad");
  HEX_MAP.set(`border-${c}-400`, "border-bad");
}

// Amber / orange -> warn
for (const c of ["amber", "orange"]) {
  HEX_MAP.set(`text-${c}-300`, "text-warn");
  HEX_MAP.set(`text-${c}-400`, "text-warn");
  HEX_MAP.set(`text-${c}-500`, "text-warn");
  HEX_MAP.set(`text-${c}-600`, "text-warn");
  HEX_MAP.set(`bg-${c}-400`, "bg-warn");
  HEX_MAP.set(`bg-${c}-500`, "bg-warn");
  HEX_MAP.set(`border-${c}-400`, "border-warn");
  HEX_MAP.set(`border-${c}-500`, "border-warn");
}

// Cyan / teal -> entity-api / info
for (const c of ["cyan", "teal"]) {
  HEX_MAP.set(`text-${c}-300`, "text-entity-api");
  HEX_MAP.set(`text-${c}-400`, "text-entity-api");
  HEX_MAP.set(`text-${c}-500`, "text-entity-api");
  HEX_MAP.set(`bg-${c}-500`, "bg-accent");
  HEX_MAP.set(`border-${c}-400`, "border-line");
  HEX_MAP.set(`border-${c}-500`, "border-line");
}

// Violet / purple / indigo -> entity-user / accent
for (const c of ["violet", "purple", "indigo"]) {
  HEX_MAP.set(`text-${c}-300`, "text-entity-user");
  HEX_MAP.set(`text-${c}-400`, "text-entity-user");
  HEX_MAP.set(`text-${c}-500`, "text-entity-user");
  HEX_MAP.set(`bg-${c}-500`, "bg-accent");
  HEX_MAP.set(`bg-${c}-600`, "bg-accent");
  HEX_MAP.set(`border-${c}-400`, "border-line");
  HEX_MAP.set(`border-${c}-500`, "border-line");
}

// Blue / sky -> entity-service / info
for (const c of ["blue", "sky"]) {
  HEX_MAP.set(`text-${c}-300`, "text-entity-service");
  HEX_MAP.set(`text-${c}-400`, "text-entity-service");
  HEX_MAP.set(`text-${c}-500`, "text-entity-service");
  HEX_MAP.set(`bg-${c}-500`, "bg-accent");
  HEX_MAP.set(`bg-${c}-600`, "bg-accent");
  HEX_MAP.set(`border-${c}-400`, "border-line");
  HEX_MAP.set(`border-${c}-500`, "border-line");
}

// Transparent / rgba / overlay classes
HEX_MAP.set("bg-[rgba(255,255,255,0.02)]", "bg-surface-2");
HEX_MAP.set("bg-[rgba(255,255,255,0.04)]", "bg-surface-2");
HEX_MAP.set("bg-[rgba(255,255,255,0.05)]", "bg-surface-2");
HEX_MAP.set("bg-[rgba(255,255,255,0.06)]", "bg-surface-2");
HEX_MAP.set("bg-[rgba(255,255,255,0.08)]", "bg-surface-2");
HEX_MAP.set("bg-white/[0.02]", "bg-surface-2");
HEX_MAP.set("bg-white/[0.04]", "bg-surface-2");
HEX_MAP.set("bg-white/[0.05]", "bg-surface-2");
HEX_MAP.set("bg-white/[0.06]", "bg-surface-2");
HEX_MAP.set("bg-white/5", "bg-surface-2");
HEX_MAP.set("bg-white/10", "bg-surface-2");
HEX_MAP.set("bg-white/15", "bg-surface-2");
HEX_MAP.set("bg-white/20", "bg-surface-2");
HEX_MAP.set("bg-black/20", "bg-surface-2");
HEX_MAP.set("bg-black/40", "bg-surface-2");

HEX_MAP.set("border-[rgba(255,255,255,0.07)]", "border-line");
HEX_MAP.set("border-[rgba(255,255,255,0.08)]", "border-line");
HEX_MAP.set("border-[rgba(255,255,255,0.1)]", "border-line");
HEX_MAP.set("border-[rgba(255,255,255,0.12)]", "border-line");
HEX_MAP.set("border-[rgba(255,255,255,0.14)]", "border-line");
HEX_MAP.set("border-[rgba(255,255,255,0.2)]", "border-line-strong");
HEX_MAP.set("border-white/10", "border-line");
HEX_MAP.set("border-white/15", "border-line");
HEX_MAP.set("border-white/20", "border-line-strong");
HEX_MAP.set("border-white/[0.08]", "border-line");

HEX_MAP.set("divide-[rgba(255,255,255,0.08)]", "divide-line");
HEX_MAP.set("divide-[rgba(255,255,255,0.07)]", "divide-line");

HEX_MAP.set("hover:bg-white/[0.05]", "hover:bg-hover");
HEX_MAP.set("hover:bg-white/[0.08]", "hover:bg-hover");
HEX_MAP.set("hover:bg-white/5", "hover:bg-hover");
HEX_MAP.set("hover:bg-white/10", "hover:bg-hover");
HEX_MAP.set("hover:bg-[#181b1f]", "hover:bg-hover");
HEX_MAP.set("hover:bg-[#202226]", "hover:bg-hover");
HEX_MAP.set("hover:bg-[#202436]", "hover:bg-hover");
HEX_MAP.set("hover:bg-[#111217]", "hover:bg-hover");
HEX_MAP.set("hover:bg-[#1f222b]", "hover:bg-hover");
HEX_MAP.set("from-[#141624]", "from-surface");
HEX_MAP.set("via-[#10121e]", "via-surface");
HEX_MAP.set("to-[#171329]", "to-surface-2");

HEX_MAP.set("text-[#56b9a8]", "text-entity-api");
HEX_MAP.set("hover:text-[#56b9a8]", "hover:text-entity-api");
HEX_MAP.set("border-[#56b9a8]", "border-entity-api");
HEX_MAP.set("border-[#56b9a8]/55", "border-entity-api/55");
HEX_MAP.set("bg-[#56b9a8]", "bg-accent-soft");
HEX_MAP.set("bg-[#56b9a8]/10", "bg-entity-api/10");

HEX_MAP.set("text-[#0d9488]", "text-entity-api");
HEX_MAP.set("text-[#82d5c4]", "text-entity-api");
HEX_MAP.set("text-[#8db7fa]", "text-entity-service");

HEX_MAP.set("text-[#5794f2]", "text-accent");
HEX_MAP.set("hover:text-[#5794f2]", "hover:text-accent");
HEX_MAP.set("border-[#5794f2]", "border-accent");
HEX_MAP.set("border-[#5794f2]/40", "border-accent/40");
HEX_MAP.set("border-[#5794f2]/55", "border-entity-service/55");
HEX_MAP.set("bg-[#5794f2]", "bg-accent");
HEX_MAP.set("bg-[#5794f2]/10", "bg-accent-soft");
HEX_MAP.set("bg-[#5794f2]/20", "bg-accent-soft");

HEX_MAP.set("focus-visible:outline-[#5794f2]", "focus-visible:outline-accent");
HEX_MAP.set("focus-visible:outline-[#1d63dc]", "focus-visible:outline-accent");
HEX_MAP.set("focus:border-[#5794f2]", "focus:border-accent");

HEX_MAP.set("text-[#1d63dc]", "text-accent");
HEX_MAP.set("hover:text-[#1d63dc]", "hover:text-accent");
HEX_MAP.set("border-[#1d63dc]", "border-accent");
HEX_MAP.set("bg-[#1d63dc]", "bg-accent");

HEX_MAP.set("text-[#b877d9]", "text-entity-user");
HEX_MAP.set("text-[#d9b4ea]", "text-entity-user");
HEX_MAP.set("border-[#b877d9]", "border-entity-user");
HEX_MAP.set("border-[#b877d9]/40", "border-entity-user/40");
HEX_MAP.set("border-[#b877d9]/55", "border-entity-user/55");
HEX_MAP.set("bg-[#b877d9]", "bg-accent-soft");
HEX_MAP.set("bg-[#b877d9]/10", "bg-entity-user/10");

HEX_MAP.set("text-[#cbd5e1]", "text-secondary");
HEX_MAP.set("text-[#334155]", "text-secondary");

HEX_MAP.set("hover:text-white", "hover:text-ink");
HEX_MAP.set("hover:text-[#fff]", "hover:text-ink");
HEX_MAP.set("hover:text-[#d8d9da]", "hover:text-ink");
HEX_MAP.set("hover:text-[#f1f3f5]", "hover:text-ink");
HEX_MAP.set("hover:text-[#f0f3f6]", "hover:text-ink");
HEX_MAP.set("hover:text-[#172235]", "hover:text-ink");

export function processSource(content, filePath) {
  const unmapped = [];
  const lines = content.split("\n");

  const PAIR_REPLACEMENTS = [
    [/\b(bg-white|bg-\[#ffffff\])\s+dark:bg-\[#(111217|141622|161826|141624|161424|18181b|10121e|0e1019)\](?=[\s"'`>]|$)/g, "bg-surface"],
    [/\bdark:bg-\[#(111217|141622|161826|141624|161424|18181b|10121e|0e1019)\]\s+(bg-white|bg-\[#ffffff\])(?=[\s"'`>]|$)/g, "bg-surface"],
    [/\b(bg-\[#f3f6fa\]|bg-\[#f3f4f8\]|bg-\[#f7f7f8\])\s+dark:bg-\[#(0b0c0e|0c0d14|0d0e12|0e0f12|0c0e17|0c0c0e)\](?=[\s"'`>]|$)/g, "bg-page"],
    [/\bdark:bg-\[#(0b0c0e|0c0d14|0d0e12|0e0f12|0c0e17|0c0c0e)\]\s+(bg-\[#f3f6fa\]|bg-\[#f3f4f8\]|bg-\[#f7f7f8\])(?=[\s"'`>]|$)/g, "bg-page"],
    [/\b(bg-\[#f1f5f9\]|bg-\[#f1f3f5\]|bg-\[#f8fafc\]|bg-slate-50|bg-slate-100)\s+dark:bg-\[#(181b1f|202226|202333|1f222b|10121c|0f111b|1e1e22|202436)\](?=[\s"'`>]|$)/g, "bg-surface-2"],
    [/\bdark:bg-\[#(181b1f|202226|202333|1f222b|10121c|0f111b|1e1e22|202436)\]\s+(bg-\[#f1f5f9\]|bg-\[#f1f3f5\]|bg-\[#f8fafc\]|bg-slate-50|bg-slate-100)(?=[\s"'`>]|$)/g, "bg-surface-2"],
    [/\b(border-\[#d5dee9\]|border-\[#e2e8f0\]|border-slate-200)\s+dark:border-\[#(303449|2a2d30|262838|34384c|34373b|2a2a30|2e3247)\](?=[\s"'`>]|$)/g, "border-line"],
    [/\bdark:border-\[#(303449|2a2d30|262838|34384c|34373b|2a2a30|2e3247)\]\s+(border-\[#d5dee9\]|border-\[#e2e8f0\]|border-slate-200)(?=[\s"'`>]|$)/g, "border-line"],
    [/\b(text-\[#172235\]|text-\[#1f2330\]|text-\[#18181b\])\s+dark:text-(white|\[#f1f3f5\]|\[#d8d9da\]|\[#f4f4f5\])(?=[\s"'`>]|$)/g, "text-ink"],
    [/\bdark:text-(white|\[#f1f3f5\]|\[#d8d9da\]|\[#f4f4f5\])\s+(text-\[#172235\]|text-\[#1f2330\]|text-\[#18181b\])(?=[\s"'`>]|$)/g, "text-ink"],
    [/\b(text-\[#475569\]|text-\[#64748b\]|text-\[#71717a\]|text-\[#334155\])\s+dark:text-\[#(a7a9ab|94a3b8|c2c6cc|a1a1aa|cbd5e1)\](?=[\s"'`>]|$)/g, "text-muted"],
    [/\bdark:text-\[#(a7a9ab|94a3b8|c2c6cc|a1a1aa|cbd5e1)\]\s+(text-\[#475569\]|text-\[#64748b\]|text-\[#71717a\]|text-\[#334155\])(?=[\s"'`>]|$)/g, "text-muted"],
    [/\bhover:bg-\[#f1f5f9\]\s+dark:hover:bg-\[#(181b1f|202226|202333|222227|202436)\](?:\/60)?(?=[\s"'`>]|$)/g, "hover:bg-hover"],
    [/\bdark:hover:bg-\[#(181b1f|202226|202333|222227|202436)\](?:\/60)?\s+hover:bg-\[#f1f5f9\](?=[\s"'`>]|$)/g, "hover:bg-hover"],
    [/\bhover:text-\[#172235\]\s+dark:hover:text-(white|\[#d8d9da\])(?=[\s"'`>]|$)/g, "hover:text-ink"],
    [/\bdark:hover:text-(white|\[#d8d9da\])\s+hover:text-\[#172235\](?=[\s"'`>]|$)/g, "hover:text-ink"],
    [/\bhover:bg-slate-100\s+dark:hover:bg-\[#202333\](?=[\s"'`>]|$)/g, "hover:bg-hover"],
    [/\bhover:text-\[#172235\]\s+dark:hover:text-white(?=[\s"'`>]|$)/g, "hover:text-ink"],
    [/\bdark:hover:text-white\s+hover:text-\[#172235\](?=[\s"'`>]|$)/g, "hover:text-ink"],
    [/\btext-\[#7c3aed\]\s+dark:text-\[#b877d9\](?=[\s"'`>]|$)/g, "text-entity-user"],
    [/\bdark:text-\[#b877d9\]\s+text-\[#7c3aed\](?=[\s"'`>]|$)/g, "text-entity-user"],
    [/\btext-\[#7c3aed\]\s+dark:text-\[#d9b4ea\](?=[\s"'`>]|$)/g, "text-entity-user"],
    [/\bdark:text-\[#d9b4ea\]\s+text-\[#7c3aed\](?=[\s"'`>]|$)/g, "text-entity-user"],
    [/\bborder-\[#7c3aed\]\/40\s+dark:border-\[#b877d9\]\/40(?=[\s"'`>]|$)/g, "border-entity-user/40"],
    [/\bdark:border-\[#b877d9\]\/40\s+border-\[#7c3aed\]\/40(?=[\s"'`>]|$)/g, "border-entity-user/40"],
    [/\bbg-\[#7c3aed\]\/10\s+dark:bg-\[#b877d9\]\/10(?=[\s"'`>]|$)/g, "bg-entity-user/10"],
    [/\bdark:bg-\[#b877d9\]\/10\s+bg-\[#7c3aed\]\/10(?=[\s"'`>]|$)/g, "bg-entity-user/10"],
    [/\btext-\[#1d63dc\]\s+dark:text-\[#a9ccff\](?=[\s"'`>]|$)/g, "text-entity-service"],
    [/\bdark:text-\[#a9ccff\]\s+text-\[#1d63dc\](?=[\s"'`>]|$)/g, "text-entity-service"],
    [/\btext-\[#1d63dc\]\s+dark:text-\[#8db7fa\](?=[\s"'`>]|$)/g, "text-entity-service"],
    [/\bdark:text-\[#8db7fa\]\s+text-\[#1d63dc\](?=[\s"'`>]|$)/g, "text-entity-service"],
    [/\btext-\[#0d9488\]\s+dark:text-\[#82d5c4\](?=[\s"'`>]|$)/g, "text-entity-api"],
    [/\bdark:text-\[#82d5c4\]\s+text-\[#0d9488\](?=[\s"'`>]|$)/g, "text-entity-api"],
    [/\btext-\[#1d63dc\]\s+dark:text-\[#5794f2\](?=[\s"'`>]|$)/g, "text-accent"],
    [/\bdark:text-\[#5794f2\]\s+text-\[#1d63dc\](?=[\s"'`>]|$)/g, "text-accent"],
    [/\bbg-\[#1d63dc\]\s+dark:bg-\[#5794f2\](?=[\s"'`>]|$)/g, "bg-accent"],
    [/\bdark:bg-\[#5794f2\]\s+bg-\[#1d63dc\](?=[\s"'`>]|$)/g, "bg-accent"],
    [/\bborder-\[#1d63dc\]\s+dark:border-\[#5794f2\](?=[\s"'`>]|$)/g, "border-accent"],
    [/\bdark:border-\[#5794f2\]\s+border-\[#1d63dc\](?=[\s"'`>]|$)/g, "border-accent"],
    [/\bhover:border-\[#1d63dc\]\s+dark:hover:border-\[#5794f2\](?:\/50)?(?=[\s"'`>]|$)/g, "hover:border-accent"],
    [/\bdark:hover:border-\[#5794f2\](?:\/50)?\s+hover:border-\[#1d63dc\](?=[\s"'`>]|$)/g, "hover:border-accent"],
    [/\bfocus-visible:outline-\[#1d63dc\]\s+dark:focus-visible:outline-\[#5794f2\](?=[\s"'`>]|$)/g, "focus-visible:outline-accent"],
    [/\bdark:focus-visible:outline-\[#5794f2\]\s+focus-visible:outline-\[#1d63dc\](?=[\s"'`>]|$)/g, "focus-visible:outline-accent"],
    [/\bhover:border-\[#c9cdd7\]\s+dark:hover:border-\[#34373b\](?=[\s"'`>]|$)/g, "hover:border-line-strong"],
    [/\bdark:hover:border-\[#34373b\]\s+hover:border-\[#c9cdd7\](?=[\s"'`>]|$)/g, "hover:border-line-strong"],
  ];

  const processedLines = lines.map((line, lineIdx) => {
    let modified = line;

    for (const [re, rep] of PAIR_REPLACEMENTS) {
      modified = modified.replace(re, rep);
    }

    // Replace Recharts common properties
    modified = modified.replace(/stroke="rgba\(255,255,255,0\.06\)"/g, 'stroke="var(--grid)"');
    modified = modified.replace(/stroke="var\(--theme-grid\)"/g, 'stroke="var(--grid)"');
    modified = modified.replace(/fill="var\(--theme-surface\)"/g, 'fill="var(--surface)"');
    modified = modified.replace(/fill="var\(--theme-text\)"/g, 'fill="var(--text)"');
    modified = modified.replace(/stroke="#303236"/g, 'stroke="var(--grid)"');

    // Replace exact mapped tokens (with optional dark: prefix)
    modified = modified.replace(/([a-zA-Z0-9_:/-]+\[[^\]]+\](?:\/[0-9]+)?|[a-zA-Z0-9_:/-]+-[a-z]+-[0-9]{2,3}|hover:[a-zA-Z0-9_:/-]+|bg-white(?:\/\[[^\]]+\]|\/[0-9]+)?|border-white(?:\/\[[^\]]+\]|\/[0-9]+)?|hover:text-white)/g, (match) => {
      const isDark = match.startsWith("dark:");
      const base = isDark ? match.slice(5) : match;
      const lower = base.toLowerCase();
      if (HEX_MAP.has(lower)) {
        return HEX_MAP.get(lower);
      }
      const alphaMatch = lower.match(/^(.+)\/([0-9]+)$/);
      if (alphaMatch && HEX_MAP.has(alphaMatch[1])) {
        return `${HEX_MAP.get(alphaMatch[1])}/${alphaMatch[2]}`;
      }
      return match;
    });

    // Check for remaining unmapped hex or dark classes
    const remainingHex = modified.matchAll(/(-?\[#[0-9a-fA-F]{3,8}\]|dark:[a-zA-Z0-9_:-]+)/g);
    for (const rm of remainingHex) {
      unmapped.push({ line: lineIdx + 1, token: rm[0], rawLine: line.trim() });
    }

    return modified;
  });

  return {
    content: processedLines.join("\n"),
    unmapped,
  };
}

// CLI runner
if (process.argv[1] && import.meta.url === `file://${path.resolve(process.argv[1])}`) {
  const args = process.argv.slice(2);
  const write = args.includes("--write");
  const files = args.filter((a) => !a.startsWith("--"));

  if (files.length === 0) {
    console.log("Usage: node scripts/restyle-codemod.mjs [--write] <file1.tsx> [file2.tsx...]");
    process.exit(1);
  }

  for (const f of files) {
    const absPath = path.resolve(process.cwd(), f);
    if (!fs.existsSync(absPath)) {
      console.error(`File not found: ${f}`);
      continue;
    }
    const content = fs.readFileSync(absPath, "utf-8");
    const { content: updated, unmapped } = processSource(content, f);

    if (write && content !== updated) {
      fs.writeFileSync(absPath, updated, "utf-8");
      console.log(`Updated: ${f}`);
    } else if (!write) {
      console.log(`Dry-run: ${f} (${unmapped.length} unmapped tokens remaining)`);
    }

    if (unmapped.length > 0) {
      console.log(`--- Unmapped tokens in ${f} (${unmapped.length}) ---`);
      for (const u of unmapped.slice(0, 30)) {
        console.log(`  ${f}:${u.line}  ${u.token}  (${u.rawLine.slice(0, 60)}...)`);
      }
      if (unmapped.length > 30) {
        console.log(`  ... and ${unmapped.length - 30} more.`);
      }
    }
  }
}
