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

/** Deterministic, bounded force layout in CSS pixels. No live simulation or grid.
 * Hubs settle toward the middle of their learned neighborhood. Initial card
 * collisions are resolved before returning; user dragging remains unrestricted.
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
  const seen = new Set<string>();
  const links = edges.flatMap(edge => {
    const a = indexes.get(edge.source); const b = indexes.get(edge.target);
    if (a === undefined || b === undefined || a === b) return [];
    const key = a < b ? `${a}:${b}` : `${b}:${a}`;
    if (seen.has(key)) return [];
    seen.add(key); degree[a]++; degree[b]++;
    return [{ a, b, weight: 0.6 + Math.min(1, Math.max(0, edge.metrics?.learning?.strength ?? 0.5)) * 0.4 }];
  }).sort((a, b) => a.a - b.a || a.b - b.b);
  const ranked = ids.map((_, index) => index).sort((a, b) => degree[b] - degree[a] || ids[a].localeCompare(ids[b]));
  const points = ids.map(() => ({ x: 0, y: 0 }));
  ranked.forEach((index, rank) => {
    const angle = rank * GOLDEN_ANGLE + 0.35;
    const radius = Math.sqrt(rank) * 105;
    points[index] = { x: Math.cos(angle) * radius, y: Math.sin(angle) * radius * 0.8 };
  });

  // Fixed iteration count bounds work at the topology's 500-service display cap.
  const iterations = ids.length > 200 ? 90 : 150;
  for (let step = 0; step < iterations; step++) {
    const forces = points.map(point => ({ x: -point.x * 0.003, y: -point.y * 0.003 }));
    for (let a = 0; a < points.length; a++) {
      for (let b = a + 1; b < points.length; b++) {
        const dx = points[b].x - points[a].x || 0.01;
        const dy = points[b].y - points[a].y || 0.01;
        const distance = Math.max(1, Math.hypot(dx, dy));
        const push = 14000 / (distance * distance);
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
    for (const { a, b, weight } of links) {
      const dx = points[b].x - points[a].x; const dy = points[b].y - points[a].y;
      const distance = Math.max(1, Math.hypot(dx, dy));
      const desired = 185 + Math.sqrt(Math.max(degree[a], degree[b])) * 12;
      const pull = (distance - desired) * 0.025 * weight;
      forces[a].x += dx / distance * pull; forces[a].y += dy / distance * pull;
      forces[b].x -= dx / distance * pull; forces[b].y -= dy / distance * pull;
    }
    const maxStep = 14 * (1 - step / iterations) + 1;
    points.forEach((point, index) => {
      const f = forces[index]; const length = Math.max(1, Math.hypot(f.x, f.y));
      const rate = Math.min(1, maxStep / length);
      point.x += f.x * rate; point.y += f.y * rate;
    });
  }

  // Keep the force result wherever possible; resolve residual rectangle overlap
  // with a local spiral search, rather than snapping cards to rows or columns.
  const placed: Position[] = [];
  for (const index of ranked) {
    const origin = points[index]; let candidate = origin; let attempt = 0;
    while (placed.some(other => Math.abs(candidate.x - other.x) < GAP_X && Math.abs(candidate.y - other.y) < GAP_Y)) {
      attempt++;
      const angle = attempt * GOLDEN_ANGLE;
      const radius = 12 * Math.sqrt(attempt);
      candidate = { x: origin.x + Math.cos(angle) * radius, y: origin.y + Math.sin(angle) * radius };
    }
    points[index] = candidate; placed.push(candidate);
  }

  const width = Math.max(1, canvasWidth); const height = Math.max(1, canvasHeight);
  const centerX = (Math.min(...points.map(p => p.x)) + Math.max(...points.map(p => p.x))) / 2;
  const centerY = (Math.min(...points.map(p => p.y)) + Math.max(...points.map(p => p.y))) / 2;
  return Object.fromEntries(ids.map((id, index) => [id, {
    x: (points[index].x - centerX + width / 2) * 1000 / width,
    y: (points[index].y - centerY + height / 2 + 30) * 620 / height,
  }]));
}
