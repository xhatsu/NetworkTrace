export type Position = { x: number; y: number };
export type LayoutNode = { id: string };
export type LayoutEdge = {
  source: string;
  target: string;
  metrics?: { request_count?: number; learning?: { strength: number } };
};

export const SERVICE_NODE_WIDTH = 156;
export const SERVICE_NODE_HEIGHT = 66;
export const SERVICE_NODE_CLEARANCE = 24;
const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));
const GAP_X = SERVICE_NODE_WIDTH + SERVICE_NODE_CLEARANCE;
const GAP_Y = SERVICE_NODE_HEIGHT + SERVICE_NODE_CLEARANCE;
const CARD_RADIUS = Math.hypot(SERVICE_NODE_WIDTH, SERVICE_NODE_HEIGHT) / 2;
// Clear space between neighbouring groups, wider than card clearance so
// separate clusters read as separate.
const GROUP_GAP = 56;
// Connected components at or below this size are kept as one group.
const SPLIT_THRESHOLD = 14;
const MIN_COMMUNITY = 3;
// Packing candidates are generated around linked groups plus this many of the
// most recently placed ones, bounding work when there are many small groups.
const RECENT_GROUPS = 16;
const PACK_ANGLES = 24;

type Link = { a: number; b: number; weight: number };
type Neighbor = { to: number; weight: number };
type Group = { members: number[]; component: number };
type Circle = { x: number; y: number; r: number };

/** Deterministic, group-first spider layout in CSS pixels.
 *
 * 1. Linked services are grouped: connected components, with large components
 *    split into densely linked communities (weighted label propagation).
 * 2. Each group gets its own bounded force layout, so members stay together.
 * 3. Groups are packed as circles. A group is placed next to the groups it
 *    links to, and communities of one component are placed consecutively.
 *    Unlinked services form a final group at the edge.
 * 4. Each placed group is rotated so its cross-group links face their partners,
 *    then residual card overlap is resolved locally.
 *
 * There is no live simulation or grid. User dragging remains unrestricted.
 */
export function layoutServiceGraph(
  nodes: LayoutNode[],
  edges: LayoutEdge[],
  canvasWidth = 1000,
  canvasHeight = 620,
  _separateOverlaps = true,
): Record<string, Position> {
  if (!nodes.length) return {};
  const ids = [...new Set(nodes.map(node => node.id))].sort();
  const indexes = new Map(ids.map((id, index) => [id, index]));
  const degree = ids.map(() => 0);
  const adjacency: Neighbor[][] = ids.map(() => []);
  const seen = new Map<string, Link>();
  for (const edge of edges) {
    const a = indexes.get(edge.source); const b = indexes.get(edge.target);
    if (a === undefined || b === undefined || a === b) continue;
    const lo = Math.min(a, b); const hi = Math.max(a, b);
    const key = `${lo}:${hi}`;
    const weight = 0.6 + Math.min(1, Math.max(0, edge.metrics?.learning?.strength ?? 0.5)) * 0.4;
    const existing = seen.get(key);
    // A bidirectional pair counts as one, stronger link.
    if (existing) { existing.weight = Math.min(1.5, existing.weight + weight * 0.5); continue; }
    seen.set(key, { a: lo, b: hi, weight });
    degree[lo]++; degree[hi]++;
  }
  const links = [...seen.values()].sort((x, y) => x.a - y.a || x.b - y.b);
  for (const { a, b, weight } of links) {
    adjacency[a].push({ to: b, weight });
    adjacency[b].push({ to: a, weight });
  }

  const groups = buildGroups(ids, adjacency, degree);
  const groupOf = ids.map(() => -1);
  groups.forEach((group, g) => group.members.forEach(index => { groupOf[index] = g; }));

  // Local layout per group, centred on the group's centroid.
  const groupLinks: Link[][] = groups.map(() => []);
  for (const link of links) if (groupOf[link.a] === groupOf[link.b]) groupLinks[groupOf[link.a]].push(link);
  const local = groups.map((group, g) => forceLayout(group.members, groupLinks[g], degree));

  // Wide canvases should grow sideways rather than downward.
  const aspect = Math.min(2.5, Math.max(0.6, Math.max(1, canvasWidth) / Math.max(1, canvasHeight)));
  const points: Position[] = ids.map(() => ({ x: 0, y: 0 }));
  const placedPoint = ids.map(() => false);
  const circles: Circle[] = [];
  groups.forEach((group, g) => {
    const offsets = local[g];
    const radius = group.members.reduce((max, index) => Math.max(max, Math.hypot(offsets.get(index)!.x, offsets.get(index)!.y)), 0) + CARD_RADIUS;

    // Attraction toward already-placed partners of this group's members.
    const partnerWeight = new Map<number, number>();
    let targetX = 0; let targetY = 0; let targetW = 0;
    for (const index of group.members) {
      for (const { to, weight } of adjacency[index]) {
        if (!placedPoint[to]) continue;
        targetX += points[to].x * weight; targetY += points[to].y * weight; targetW += weight;
        partnerWeight.set(groupOf[to], (partnerWeight.get(groupOf[to]) ?? 0) + weight);
      }
    }
    const anchor = targetW ? { x: targetX / targetW, y: targetY / targetW } : { x: 0, y: 0 };
    const center = packCircle(circles, radius, anchor, [...partnerWeight.keys()], aspect);
    circles.push({ ...center, r: radius });

    // Rotate so members with cross-group links face their partners.
    let rotation = 0;
    if (targetW) {
      let portX = 0; let portY = 0;
      for (const index of group.members) {
        const w = adjacency[index].reduce((sum, n) => sum + (placedPoint[n.to] ? n.weight : 0), 0);
        portX += offsets.get(index)!.x * w; portY += offsets.get(index)!.y * w;
      }
      const toPartner = Math.atan2(anchor.y - center.y, anchor.x - center.x);
      if (Math.hypot(portX, portY) > 1 && Math.hypot(anchor.x - center.x, anchor.y - center.y) > 1) {
        rotation = toPartner - Math.atan2(portY, portX);
      }
    }
    const cos = Math.cos(rotation); const sin = Math.sin(rotation);
    const rotated = group.members.map(index => {
      const p = offsets.get(index)!;
      return { index, x: p.x * cos - p.y * sin, y: p.x * sin + p.y * cos };
    });
    // Rotation keeps distances but not axis-aligned card clearance.
    separate(rotated);
    for (const p of rotated) { points[p.index] = { x: center.x + p.x, y: center.y + p.y }; placedPoint[p.index] = true; }
  });

  // Final safety pass across groups, preserving group order.
  const ordered = groups.flatMap(group => group.members).map(index => ({ index, ...points[index] }));
  separate(ordered);
  for (const p of ordered) points[p.index] = { x: p.x, y: p.y };

  const width = Math.max(1, canvasWidth); const height = Math.max(1, canvasHeight);
  const centerX = (Math.min(...points.map(p => p.x)) + Math.max(...points.map(p => p.x))) / 2;
  const centerY = (Math.min(...points.map(p => p.y)) + Math.max(...points.map(p => p.y))) / 2;
  return Object.fromEntries(ids.map((id, index) => [id, {
    x: (points[index].x - centerX + width / 2) * 1000 / width,
    y: (points[index].y - centerY + height / 2 + 30) * 620 / height,
  }]));
}

/** Groups in placement order: components by size, each component's communities
 * in breadth-first order from its largest one, and unlinked services last. */
function buildGroups(ids: string[], adjacency: Neighbor[][], degree: number[]): Group[] {
  const component = ids.map(() => -1);
  const components: number[][] = [];
  const isolated: number[] = [];
  for (let start = 0; start < ids.length; start++) {
    if (component[start] >= 0) continue;
    if (!adjacency[start].length) { isolated.push(start); continue; }
    const members = [start]; component[start] = components.length;
    for (let cursor = 0; cursor < members.length; cursor++) {
      for (const { to } of adjacency[members[cursor]]) {
        if (component[to] < 0) { component[to] = components.length; members.push(to); }
      }
    }
    components.push(members.sort((a, b) => a - b));
  }
  const componentOrder = components.map((_, c) => c)
    .sort((a, b) => components[b].length - components[a].length || components[a][0] - components[b][0]);

  const groups: Group[] = [];
  for (const c of componentOrder) {
    const members = components[c];
    if (members.length <= SPLIT_THRESHOLD) { groups.push({ members, component: c }); continue; }
    const communities = splitCommunities(members, adjacency, degree);
    // Breadth-first over community links so every community after the first
    // is placed beside one it connects to.
    const communityOf = new Map<number, number>();
    communities.forEach((list, k) => list.forEach(index => communityOf.set(index, k)));
    const strength = communities.map(() => new Map<number, number>());
    for (const index of members) {
      for (const { to, weight } of adjacency[index]) {
        const a = communityOf.get(index)!; const b = communityOf.get(to)!;
        if (a !== b) strength[a].set(b, (strength[a].get(b) ?? 0) + weight);
      }
    }
    const visited = communities.map(() => false);
    const queue = [0]; visited[0] = true;
    for (let cursor = 0; cursor < queue.length; cursor++) {
      const k = queue[cursor];
      groups.push({ members: communities[k], component: c });
      const next = [...strength[k].entries()].filter(([to]) => !visited[to]).sort((x, y) => y[1] - x[1] || x[0] - y[0]);
      for (const [to] of next) { visited[to] = true; queue.push(to); }
    }
  }
  if (isolated.length) groups.push({ members: isolated, component: -1 });
  return groups;
}

/** Deterministic weighted label propagation. Returns communities sorted by
 * size (largest first); communities below MIN_COMMUNITY merge into their most
 * strongly linked neighbour. */
function splitCommunities(members: number[], adjacency: Neighbor[][], degree: number[]): number[][] {
  const label = new Map(members.map(index => [index, index]));
  const order = [...members].sort((a, b) => degree[b] - degree[a] || a - b);
  for (let round = 0; round < 30; round++) {
    let changed = false;
    for (const index of order) {
      const tally = new Map<number, number>();
      for (const { to, weight } of adjacency[index]) tally.set(label.get(to)!, (tally.get(label.get(to)!) ?? 0) + weight);
      const current = label.get(index)!;
      let best = current; let bestWeight = tally.get(current) ?? -1;
      for (const [candidate, weight] of tally) {
        if (weight > bestWeight + 1e-9 || (Math.abs(weight - bestWeight) <= 1e-9 && candidate < best && best !== current)) {
          best = candidate; bestWeight = weight;
        }
      }
      if (best !== current) { label.set(index, best); changed = true; }
    }
    if (!changed) break;
  }

  const merge = () => {
    const sizes = new Map<number, number>();
    for (const index of members) sizes.set(label.get(index)!, (sizes.get(label.get(index)!) ?? 0) + 1);
    const small = [...sizes.entries()].filter(([, size]) => size < MIN_COMMUNITY).sort((a, b) => a[1] - b[1] || a[0] - b[0]);
    if (!small.length || sizes.size === 1) return false;
    const [target] = small[0];
    const pull = new Map<number, number>();
    for (const index of members) {
      if (label.get(index) !== target) continue;
      for (const { to, weight } of adjacency[index]) {
        const other = label.get(to)!;
        if (other !== target) pull.set(other, (pull.get(other) ?? 0) + weight);
      }
    }
    const into = [...pull.entries()].sort((a, b) => b[1] - a[1] || a[0] - b[0])[0]?.[0];
    if (into === undefined) return false;
    for (const index of members) if (label.get(index) === target) label.set(index, into);
    return true;
  };
  while (merge()) { /* repeat until every community is large enough */ }

  const byLabel = new Map<number, number[]>();
  for (const index of members) {
    const list = byLabel.get(label.get(index)!) ?? [];
    list.push(index); byLabel.set(label.get(index)!, list);
  }
  return [...byLabel.values()].sort((a, b) => b.length - a.length || a[0] - b[0]);
}

/** Bounded force layout for one group. Returns offsets from the group centroid. */
function forceLayout(members: number[], links: Link[], degree: number[]): Map<number, Position> {
  const localIndex = new Map(members.map((index, i) => [index, i]));
  const ranked = members.map((_, i) => i).sort((a, b) => degree[members[b]] - degree[members[a]] || members[a] - members[b]);
  const points = members.map(() => ({ x: 0, y: 0 }));
  ranked.forEach((i, rank) => {
    const angle = rank * GOLDEN_ANGLE + 0.35;
    const radius = Math.sqrt(rank) * 95;
    points[i] = { x: Math.cos(angle) * radius, y: Math.sin(angle) * radius * 0.8 };
  });
  const localLinks = links.map(link => ({ a: localIndex.get(link.a)!, b: localIndex.get(link.b)!, weight: link.weight }));
  const localDegree = members.map(index => degree[index]);

  if (members.length > 1) {
    // Fixed iteration count bounds work at the topology's 500-service display cap.
    const iterations = members.length > 200 ? 90 : 150;
    // Stronger gravity for linked groups keeps them compact; unlinked services
    // only need a tidy disc.
    const gravity = localLinks.length ? 0.006 : 0.012;
    for (let step = 0; step < iterations; step++) {
      const forces = points.map(point => ({ x: -point.x * gravity, y: -point.y * gravity }));
      for (let a = 0; a < points.length; a++) {
        for (let b = a + 1; b < points.length; b++) {
          const dx = points[b].x - points[a].x || 0.01;
          const dy = points[b].y - points[a].y || 0.01;
          const distance = Math.max(1, Math.hypot(dx, dy));
          const push = 12000 / (distance * distance);
          const fx = dx / distance * push; const fy = dy / distance * push;
          forces[a].x -= fx; forces[a].y -= fy;
          forces[b].x += fx; forces[b].y += fy;
          const overlapX = GAP_X - Math.abs(dx); const overlapY = GAP_Y - Math.abs(dy);
          if (overlapX > 0 && overlapY > 0) {
            if (overlapX / GAP_X < overlapY / GAP_Y) {
              const shift = Math.sign(dx) * (overlapX + 1) * 0.3;
              forces[a].x -= shift; forces[b].x += shift;
            } else {
              const shift = Math.sign(dy) * (overlapY + 1) * 0.3;
              forces[a].y -= shift; forces[b].y += shift;
            }
          }
        }
      }
      for (const { a, b, weight } of localLinks) {
        const dx = points[b].x - points[a].x; const dy = points[b].y - points[a].y;
        const distance = Math.max(1, Math.hypot(dx, dy));
        const desired = 170 + Math.sqrt(Math.max(localDegree[a], localDegree[b])) * 10;
        const pull = (distance - desired) * 0.03 * weight;
        forces[a].x += dx / distance * pull; forces[a].y += dy / distance * pull;
        forces[b].x -= dx / distance * pull; forces[b].y -= dy / distance * pull;
      }
      const maxStep = 14 * (1 - step / iterations) + 1;
      points.forEach((point, i) => {
        const f = forces[i]; const length = Math.max(1, Math.hypot(f.x, f.y));
        const rate = Math.min(1, maxStep / length);
        point.x += f.x * rate; point.y += f.y * rate;
      });
    }
  }

  const ordered = ranked.map(i => ({ index: members[i], x: points[i].x, y: points[i].y }));
  separate(ordered);
  const cx = ordered.reduce((sum, p) => sum + p.x, 0) / ordered.length;
  const cy = ordered.reduce((sum, p) => sum + p.y, 0) / ordered.length;
  return new Map(ordered.map(p => [p.index, { x: p.x - cx, y: p.y - cy }]));
}

/** Resolve card rectangle overlap in list order with a local spiral search,
 * keeping each card as close to its computed position as possible. */
function separate(list: { x: number; y: number }[]) {
  const placed: Position[] = [];
  for (const point of list) {
    const origin = { x: point.x, y: point.y }; let candidate = origin; let attempt = 0;
    while (placed.some(other => Math.abs(candidate.x - other.x) < GAP_X && Math.abs(candidate.y - other.y) < GAP_Y)) {
      attempt++;
      const angle = attempt * GOLDEN_ANGLE;
      const radius = 12 * Math.sqrt(attempt);
      candidate = { x: origin.x + Math.cos(angle) * radius, y: origin.y + Math.sin(angle) * radius };
    }
    point.x = candidate.x; point.y = candidate.y; placed.push(candidate);
  }
}

/** Place a circle of radius r touching existing groups, as close as possible to
 * the anchor (its linked partners, or the origin), without intersecting any. */
function packCircle(circles: Circle[], r: number, anchor: Position, partners: number[], aspect: number): Position {
  if (!circles.length) return { x: 0, y: 0 };
  const around = new Set(partners);
  for (let g = Math.max(0, circles.length - RECENT_GROUPS); g < circles.length; g++) around.add(g);
  // A linked group should hug its partners; an unlinked one should keep the
  // overall picture compact.
  const linked = partners.length > 0;
  let best: Position | null = null; let bestScore = Infinity;
  for (const g of [...around].sort((a, b) => a - b)) {
    const base = circles[g];
    for (let k = 0; k < PACK_ANGLES; k++) {
      const angle = (k / PACK_ANGLES) * Math.PI * 2;
      const distance = base.r + r + GROUP_GAP;
      const candidate = { x: base.x + Math.cos(angle) * distance, y: base.y + Math.sin(angle) * distance };
      if (circles.some(other => Math.hypot(candidate.x - other.x, candidate.y - other.y) < other.r + r + GROUP_GAP - 0.5)) continue;
      const toAnchor = Math.hypot(candidate.x - anchor.x, candidate.y - anchor.y);
      // Elliptical distance matching the canvas shape keeps the picture fitting the viewport.
      const toOrigin = Math.hypot(candidate.x / aspect, candidate.y);
      const score = linked ? toAnchor + toOrigin * 0.15 : toOrigin;
      if (score < bestScore - 1e-6) { bestScore = score; best = candidate; }
    }
  }
  if (best) return best;
  // Fallback: outside everything placed so far.
  const extent = circles.reduce((max, c) => Math.max(max, Math.hypot(c.x, c.y) + c.r), 0);
  return { x: extent + r + GROUP_GAP, y: 0 };
}
