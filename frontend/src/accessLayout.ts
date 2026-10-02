import type { AccessColumn, AccessLink, AccessNode } from "./accessEncoding";

// Classic Sankey geometry: thin node bars, labels beside them, ribbons between.
export const BAR_W = 8;
export const MIN_STEP = 190;      // below this the chart scrolls inside its own container
export const HEADER_H = 26;
const SLOT_MIN = 32;              // vertical room a node needs for its two label lines
const NODE_GAP = 6;
// Dense columns drop the metric line (it moves to the inspector/tooltip) and pack tighter.
export const COMPACT_AT = 16;
const SLOT_COMPACT = 17;
const GAP_COMPACT = 3;
const ORDER_SWEEPS = 4;
const PAD_X = 4;
const PAD_BOTTOM = 8;
export const UNKNOWN_RIBBON = 3;  // peer-IP ribbons have no measured volume
export const MIN_RIBBON = 4;      // small credentials stay visible and clickable-looking
const MIN_BAR = 10;               // minimum bar height for any measured item

export type PlacedNode = AccessNode & { x: number; y: number; h: number; col: number; labelWidth: number };
export type PlacedLink = AccessLink & { path: string; top: string; bottom: string; mx: number; my: number; thickness: number };

const ORDER: AccessColumn[] = ["caller", "credential", "service", "api", "ip"];

export function layoutFlow(nodes: AccessNode[], links: AccessLink[], containerWidth: number) {
  const columns = ORDER.filter(kind => nodes.some(n => n.kind === kind));
  const byCol = new Map<AccessColumn, AccessNode[]>(columns.map(kind => [kind, nodes.filter(n => n.kind === kind)]));
  const count = columns.length;
  // Room right of the last column for its labels; wider cards give long API names more space.
  const LABEL_W = Math.round(Math.min(280, Math.max(170, containerWidth * 0.2)));
  const step = count > 1 ? Math.max(MIN_STEP, (containerWidth - LABEL_W - PAD_X * 2 - BAR_W) / (count - 1)) : 0;
  const width = count > 1 ? PAD_X * 2 + step * (count - 1) + BAR_W + LABEL_W : Math.max(containerWidth, BAR_W + LABEL_W + PAD_X * 2);

  const tallest = Math.max(1, ...[...byCol.values()].map(list => list.length));
  const compact = tallest >= COMPACT_AT;
  const slot = compact ? SLOT_COMPACT : SLOT_MIN;
  const gap = compact ? GAP_COMPACT : NODE_GAP;
  // Fill a generous band so ribbons read as volumes, not hairlines.
  const plotH = Math.min(compact ? 720 : 560, Math.max(300, tallest * (slot + gap)));

  // One px-per-TPS scale shared by every column so ribbon thickness stays comparable.
  let scale = Infinity;
  for (const [kind, list] of byCol) {
    if (kind === "ip") continue;
    const total = list.reduce((sum, n) => sum + (n.width_tps ?? 0), 0);
    const room = plotH - gap * Math.max(0, list.length - 1) - list.length * MIN_RIBBON;
    if (total > 0) scale = Math.min(scale, Math.max(80, room) / total);
  }
  if (!Number.isFinite(scale)) scale = 1;

  const thickness = (l: AccessLink) => (l.volume_known ? Math.max(MIN_RIBBON, (l.width_tps || 0) * scale) : UNKNOWN_RIBBON);
  const usable = links.filter(l => byCol.get(l.from_column)?.some(n => n.id === l.source) && byCol.get(l.to_column)?.some(n => n.id === l.target));
  const outSum = new Map<string, number>();
  const inSum = new Map<string, number>();
  usable.forEach(l => {
    outSum.set(l.source, (outSum.get(l.source) || 0) + thickness(l));
    inSum.set(l.target, (inSum.get(l.target) || 0) + thickness(l));
  });
  const barHeight = (n: AccessNode) => {
    const volume = n.width_tps == null ? 0 : n.width_tps * scale;
    return Math.max(n.width_tps == null ? 3 : MIN_BAR, volume, outSum.get(n.id) || 0, inSum.get(n.id) || 0);
  };

  const outgoing = new Map<string, AccessLink[]>();
  const incoming = new Map<string, AccessLink[]>();
  usable.forEach(l => {
    if (!outgoing.has(l.source)) outgoing.set(l.source, []);
    if (!incoming.has(l.target)) incoming.set(l.target, []);
    outgoing.get(l.source)!.push(l);
    incoming.get(l.target)!.push(l);
  });

  // Crossing reduction: alternate left/right barycenter sweeps, weighted by ribbon thickness.
  // "Other" and IP role groups stay pinned at the bottom of their column.
  const rel = new Map<string, number>();
  const remember = (list: AccessNode[]) => list.forEach((n, i) => rel.set(n.id, list.length > 1 ? i / (list.length - 1) : 0.5));
  byCol.forEach(remember);
  const reorder = (kind: AccessColumn, side: Map<string, AccessLink[]>, other: (l: AccessLink) => string) => {
    const list = byCol.get(kind)!;
    const bary = new Map<string, number>();
    for (const n of list) {
      let sum = 0;
      let weight = 0;
      for (const l of side.get(n.id) || []) {
        const w = thickness(l);
        sum += rel.get(other(l))! * w;
        weight += w;
      }
      bary.set(n.id, weight ? sum / weight : rel.get(n.id)!);
    }
    const pinned = (n: AccessNode) => (n.other || n.group ? 1 : 0);
    list.sort((a, b) => pinned(a) - pinned(b) || bary.get(a.id)! - bary.get(b.id)! || rel.get(a.id)! - rel.get(b.id)!);
    remember(list);
  };
  for (let sweep = 0; sweep < ORDER_SWEEPS; sweep++) {
    if (sweep % 2 === 0) columns.slice(1).forEach(kind => reorder(kind, incoming, l => l.source));
    else columns.slice(0, -1).reverse().forEach(kind => reorder(kind, outgoing, l => l.target));
  }

  const placed: PlacedNode[] = [];
  const columnHeights = columns.map(kind => (byCol.get(kind) || []).reduce((sum, n) => sum + Math.max(barHeight(n), slot) + gap, -gap));
  const maxColumn = Math.max(...columnHeights, 0);
  columns.forEach((kind, col) => {
    // Centre shorter columns against the tallest so flows read as a balanced band.
    let y = HEADER_H + (maxColumn - columnHeights[col]) / 2;
    const x = PAD_X + col * step;
    const labelWidth = col === count - 1 ? LABEL_W - 12 : Math.max(80, step - BAR_W - 22);
    for (const n of byCol.get(kind) || []) {
      const h = barHeight(n);
      placed.push({ ...n, x, y, h, col, labelWidth });
      y += Math.max(h, slot) + gap;
    }
  });
  const index = new Map(placed.map(n => [n.id, n]));

  // Stack ribbons on each bar in the order of their counterpart to minimise crossings.
  const out0 = new Map<string, number>();
  const in0 = new Map<string, number>();
  for (const n of placed) {
    let cursor = n.y + (n.h - (outSum.get(n.id) || 0)) / 2;
    (outgoing.get(n.id) || []).sort((a, b) => index.get(a.target)!.y - index.get(b.target)!.y)
      .forEach(l => { out0.set(l.id, cursor); cursor += thickness(l); });
    cursor = n.y + (n.h - (inSum.get(n.id) || 0)) / 2;
    (incoming.get(n.id) || []).sort((a, b) => index.get(a.source)!.y - index.get(b.source)!.y)
      .forEach(l => { in0.set(l.id, cursor); cursor += thickness(l); });
  }

  const placedLinks: PlacedLink[] = usable.map(l => {
    const a = index.get(l.source)!;
    const b = index.get(l.target)!;
    const t = thickness(l);
    const y0 = out0.get(l.id)!;
    const y1 = in0.get(l.id)!;
    const x0 = a.x + BAR_W;
    const x1 = b.x;
    const xm = (x0 + x1) / 2;
    const top = `M${x0},${y0} C${xm},${y0} ${xm},${y1} ${x1},${y1}`;
    const bottom = `M${x0},${y0 + t} C${xm},${y0 + t} ${xm},${y1 + t} ${x1},${y1 + t}`;
    const path = `${top} L${x1},${y1 + t} C${xm},${y1 + t} ${xm},${y0 + t} ${x0},${y0 + t} Z`;
    return { ...l, path, top, bottom, thickness: t, mx: xm, my: (y0 + y1 + t) / 2 };
  });

  return {
    columns,
    columnX: columns.map((_, col) => PAD_X + col * step),
    nodes: placed,
    links: placedLinks,
    compact,
    width,
    height: HEADER_H + maxColumn + PAD_BOTTOM,
  };
}
