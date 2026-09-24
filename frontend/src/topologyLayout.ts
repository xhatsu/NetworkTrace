export type Position = {
  x: number;
  y: number;
};

export type LayoutNode = {
  id: string;
};

export type LayoutEdge = {
  source: string;
  target: string;
  metrics?: {
    request_count?: number;
  };
};

const LAYER_GAP = 260;
const NODE_GAP = 110;
const COMPONENT_GAP = 220;
const MAX_NODES_PER_COLUMN = 14;
const CROSSING_SWEEPS = 8;

const SERVICE_CARD_HALF_WIDTH = 88;
const SERVICE_CARD_HALF_HEIGHT = 40;
const SCC_RADIUS = 122;
const SCC_GRID_X_GAP = 220;
const SCC_GRID_Y_GAP = 170;

type SccGroup = {
  id: string;
  members: string[];
  outgoing: Map<string, number>;
  incoming: Map<string, number>;
  layer: number;
  halfWidth: number;
  halfHeight: number;
};

type VisualColumn = {
  groups: SccGroup[];
  offsetX: number;
  height: number;
};

function edgeWeight(edge: LayoutEdge): number {
  const count = edge.metrics?.request_count;
  const safeCount = typeof count === "number" && Number.isFinite(count) && count >= 0 ? count : 1;
  return Math.max(1, Math.log1p(safeCount));
}

function compareIds(left: string, right: string): number {
  return left.localeCompare(right);
}

function stronglyConnectedComponents(
  nodeIds: string[],
  outgoing: Map<string, Set<string>>,
): string[][] {
  let nextIndex = 0;
  const indexById = new Map<string, number>();
  const lowLinkById = new Map<string, number>();
  const stack: string[] = [];
  const onStack = new Set<string>();
  const components: string[][] = [];

  function visit(nodeId: string) {
    const index = nextIndex;
    nextIndex += 1;
    indexById.set(nodeId, index);
    lowLinkById.set(nodeId, index);
    stack.push(nodeId);
    onStack.add(nodeId);

    const neighbors = [...(outgoing.get(nodeId) || [])].sort(compareIds);
    for (const neighborId of neighbors) {
      if (!indexById.has(neighborId)) {
        visit(neighborId);
        lowLinkById.set(nodeId, Math.min(lowLinkById.get(nodeId) ?? index, lowLinkById.get(neighborId) ?? index));
      } else if (onStack.has(neighborId)) {
        lowLinkById.set(nodeId, Math.min(lowLinkById.get(nodeId) ?? index, indexById.get(neighborId) ?? index));
      }
    }

    if (lowLinkById.get(nodeId) !== indexById.get(nodeId)) return;
    const component: string[] = [];
    let memberId: string | undefined;
    do {
      memberId = stack.pop();
      if (memberId === undefined) break;
      onStack.delete(memberId);
      component.push(memberId);
    } while (memberId !== nodeId);
    component.sort(compareIds);
    components.push(component);
  }

  for (const nodeId of [...nodeIds].sort(compareIds)) {
    if (!indexById.has(nodeId)) visit(nodeId);
  }
  return components;
}

function weightedMedian(values: Array<{ value: number; weight: number }>): number {
  const ordered = [...values].sort((left, right) => left.value - right.value);
  const totalWeight = ordered.reduce((sum, item) => sum + item.weight, 0);
  let seenWeight = 0;
  for (const item of ordered) {
    seenWeight += item.weight;
    if (seenWeight >= totalWeight / 2) return item.value;
  }
  return ordered[ordered.length - 1]?.value ?? 0;
}

function crossingScore(
  group: SccGroup,
  layerIndex: number,
  layers: string[][],
  layerPositions: Map<string, number>,
  groupsById: Map<string, SccGroup>,
  direction: "left" | "right",
): number | undefined {
  const adjacentLayerIndex = direction === "left" ? layerIndex - 1 : layerIndex + 1;
  const adjacentLayer = layers[adjacentLayerIndex];
  if (!adjacentLayer) return undefined;
  const adjacentIds = new Set(adjacentLayer);
  const weights = direction === "left" ? group.incoming : group.outgoing;
  const neighbors: Array<{ value: number; weight: number }> = [];
  for (const [neighborId, weight] of weights) {
    if (!adjacentIds.has(neighborId)) continue;
    const position = layerPositions.get(neighborId);
    if (position !== undefined && groupsById.has(neighborId)) neighbors.push({ value: position, weight });
  }
  if (!neighbors.length) return undefined;
  const median = weightedMedian(neighbors);
  const weightedAverage = neighbors.reduce((sum, item) => sum + item.value * item.weight, 0)
    / neighbors.reduce((sum, item) => sum + item.weight, 0);
  return median * 0.7 + weightedAverage * 0.3;
}

function groupSizeMetrics(size: number): { halfWidth: number; halfHeight: number } {
  if (size <= 1) {
    return { halfWidth: SERVICE_CARD_HALF_WIDTH, halfHeight: SERVICE_CARD_HALF_HEIGHT };
  }
  if (size <= 3) {
    return {
      halfWidth: SCC_RADIUS + SERVICE_CARD_HALF_WIDTH,
      halfHeight: SCC_RADIUS + SERVICE_CARD_HALF_HEIGHT,
    };
  }
  const columns = Math.ceil(Math.sqrt(size));
  const rows = Math.ceil(size / columns);
  return {
    halfWidth: ((columns - 1) * SCC_GRID_X_GAP) / 2 + SERVICE_CARD_HALF_WIDTH,
    halfHeight: ((rows - 1) * SCC_GRID_Y_GAP) / 2 + SERVICE_CARD_HALF_HEIGHT,
  };
}

function buildVisualColumns(groups: SccGroup[]): VisualColumn[] {
  const columns: VisualColumn[] = [];
  let currentGroups: SccGroup[] = [];
  let currentNodeCount = 0;

  function finishColumn() {
    if (!currentGroups.length) return;
    const height = currentGroups.reduce((sum, group) => sum + group.halfHeight * 2, 0)
      + NODE_GAP * Math.max(0, currentGroups.length - 1);
    columns.push({ groups: currentGroups, offsetX: 0, height });
    currentGroups = [];
    currentNodeCount = 0;
  }

  for (const group of groups) {
    if (currentGroups.length && currentNodeCount + group.members.length > MAX_NODES_PER_COLUMN) finishColumn();
    currentGroups.push(group);
    currentNodeCount += group.members.length;
    if (currentNodeCount >= MAX_NODES_PER_COLUMN) finishColumn();
  }
  finishColumn();

  for (let index = 1; index < columns.length; index += 1) {
    const previous = columns[index - 1];
    const current = columns[index];
    if (!previous || !current) continue;
    const previousHalfWidth = Math.max(...previous.groups.map((group) => group.halfWidth));
    const currentHalfWidth = Math.max(...current.groups.map((group) => group.halfWidth));
    current.offsetX = previous.offsetX + previousHalfWidth + currentHalfWidth + 24;
  }
  return columns;
}

function componentLayout(
  componentNodes: string[],
  componentEdges: LayoutEdge[],
): { positions: Record<string, Position>; height: number } {
  const nodeSet = new Set(componentNodes);
  const adjacency = new Map<string, Set<string>>();
  for (const nodeId of componentNodes) adjacency.set(nodeId, new Set());
  for (const edge of componentEdges) {
    if (!nodeSet.has(edge.source) || !nodeSet.has(edge.target)) continue;
    adjacency.get(edge.source)?.add(edge.target);
  }

  const sccs = stronglyConnectedComponents(componentNodes, adjacency);
  const groupIdByNode = new Map<string, string>();
  const groupsById = new Map<string, SccGroup>();
  sccs.forEach((members, index) => {
    const groupId = `scc:${index}:${members[0] || ""}`;
    const size = groupSizeMetrics(members.length);
    const group: SccGroup = {
      id: groupId,
      members,
      outgoing: new Map(),
      incoming: new Map(),
      layer: 0,
      halfWidth: size.halfWidth,
      halfHeight: size.halfHeight,
    };
    groupsById.set(groupId, group);
    for (const nodeId of members) groupIdByNode.set(nodeId, groupId);
  });

  const groupAdjacency = new Map<string, Set<string>>();
  const weightedEdges = new Map<string, Map<string, number>>();
  for (const groupId of groupsById.keys()) {
    groupAdjacency.set(groupId, new Set());
    weightedEdges.set(groupId, new Map());
  }
  for (const edge of componentEdges) {
    const sourceGroupId = groupIdByNode.get(edge.source);
    const targetGroupId = groupIdByNode.get(edge.target);
    if (!sourceGroupId || !targetGroupId || sourceGroupId === targetGroupId) continue;
    groupAdjacency.get(sourceGroupId)?.add(targetGroupId);
    const targets = weightedEdges.get(sourceGroupId);
    if (targets) targets.set(targetGroupId, (targets.get(targetGroupId) || 0) + edgeWeight(edge));
  }
  for (const [sourceId, targets] of weightedEdges) {
    for (const [targetId, weight] of targets) {
      groupsById.get(sourceId)?.outgoing.set(targetId, weight);
      groupsById.get(targetId)?.incoming.set(sourceId, weight);
    }
  }

  const indegree = new Map<string, number>();
  for (const groupId of groupsById.keys()) indegree.set(groupId, 0);
  for (const targets of groupAdjacency.values()) {
    for (const targetId of targets) indegree.set(targetId, (indegree.get(targetId) || 0) + 1);
  }
  const ready = [...indegree].filter(([, degree]) => degree === 0).map(([groupId]) => groupId).sort(compareIds);
  while (ready.length) {
    const groupId = ready.shift();
    if (!groupId) continue;
    const targets = [...(groupAdjacency.get(groupId) || [])].sort(compareIds);
    for (const targetId of targets) {
      const nextIndegree = (indegree.get(targetId) || 0) - 1;
      indegree.set(targetId, nextIndegree);
      if (nextIndegree === 0) {
        ready.push(targetId);
        ready.sort(compareIds);
      }
      const sourceGroup = groupsById.get(groupId);
      const targetGroup = groupsById.get(targetId);
      if (sourceGroup && targetGroup) targetGroup.layer = Math.max(targetGroup.layer, sourceGroup.layer + 1);
    }
  }

  const maxLayer = Math.max(0, ...[...groupsById.values()].map((group) => group.layer));
  const layers: string[][] = Array.from({ length: maxLayer + 1 }, () => []);
  for (const group of groupsById.values()) layers[group.layer]?.push(group.id);
  for (const layer of layers) layer.sort(compareIds);

  for (let sweep = 0; sweep < CROSSING_SWEEPS; sweep += 1) {
    const direction = sweep % 2 === 0 ? "left" : "right";
    const layerIndexes = direction === "left"
      ? Array.from({ length: layers.length }, (_, index) => index)
      : Array.from({ length: layers.length }, (_, index) => layers.length - index - 1);
    for (const layerIndex of layerIndexes) {
      const layer = layers[layerIndex];
      const adjacentLayerIndex = direction === "left" ? layerIndex - 1 : layerIndex + 1;
      const adjacentLayerPositions = new Map((layers[adjacentLayerIndex] || []).map((groupId, index) => [groupId, index]));
      const scored = layer.map((groupId, originalIndex) => {
        const group = groupsById.get(groupId);
        const score = group
          ? crossingScore(group, layerIndex, layers, adjacentLayerPositions, groupsById, direction)
          : undefined;
        return { groupId, originalIndex, score };
      });
      scored.sort((left, right) => {
        if (left.score !== undefined && right.score !== undefined && left.score !== right.score) return left.score - right.score;
        if (left.score !== undefined && right.score === undefined) return -1;
        if (left.score === undefined && right.score !== undefined) return 1;
        return left.originalIndex - right.originalIndex || compareIds(left.groupId, right.groupId);
      });
      layers[layerIndex] = scored.map((item) => item.groupId);
    }
  }

  const columnsByLayer = layers.map((layer) => buildVisualColumns(
    layer.map((groupId) => groupsById.get(groupId)).filter((group): group is SccGroup => group !== undefined),
  ));
  const maxColumnHeight = Math.max(0, ...columnsByLayer.flatMap((columns) => columns.map((column) => column.height)));
  const positions: Record<string, Position> = {};
  let layerX = 100;

  columnsByLayer.forEach((columns, layerIndex) => {
    let rightExtent = 0;
    for (const column of columns) {
      let cursorY = (maxColumnHeight - column.height) / 2;
      for (const group of column.groups) {
        const centerX = layerX + column.offsetX;
        const centerY = cursorY + group.halfHeight;
        const size = group.members.length;
        if (size === 1) {
          const memberId = group.members[0];
          if (memberId) positions[memberId] = { x: centerX, y: centerY };
        } else if (size <= 3) {
          group.members.forEach((memberId, index) => {
            const angle = -Math.PI / 2 + (Math.PI * 2 * index) / size;
            positions[memberId] = {
              x: centerX + Math.cos(angle) * SCC_RADIUS,
              y: centerY + Math.sin(angle) * SCC_RADIUS,
            };
          });
        } else {
          const gridColumns = Math.ceil(Math.sqrt(size));
          const gridRows = Math.ceil(size / gridColumns);
          group.members.forEach((memberId, index) => {
            const row = Math.floor(index / gridColumns);
            const columnIndex = index % gridColumns;
            positions[memberId] = {
              x: centerX + (columnIndex - (gridColumns - 1) / 2) * SCC_GRID_X_GAP,
              y: centerY + (row - (gridRows - 1) / 2) * SCC_GRID_Y_GAP,
            };
          });
        }
        rightExtent = Math.max(rightExtent, column.offsetX + group.halfWidth);
        cursorY += group.halfHeight * 2 + NODE_GAP;
      }
    }
    if (layerIndex < columnsByLayer.length - 1) {
      const nextLayerLeftExtent = Math.max(
        SERVICE_CARD_HALF_WIDTH,
        ...((columnsByLayer[layerIndex + 1]?.[0]?.groups || []).map((group) => group.halfWidth)),
      );
      const desiredCardGap = LAYER_GAP - SERVICE_CARD_HALF_WIDTH * 2;
      layerX += Math.max(LAYER_GAP, rightExtent + nextLayerLeftExtent + desiredCardGap);
    }
  });

  return { positions, height: maxColumnHeight };
}

function findWeakComponents(nodes: LayoutNode[], edges: LayoutEdge[]): Array<{ nodeIds: string[]; edges: LayoutEdge[] }> {
  const nodeIds = [...new Set(nodes.map((node) => node.id))].sort(compareIds);
  const nodeSet = new Set(nodeIds);
  const adjacency = new Map(nodeIds.map((nodeId) => [nodeId, new Set<string>()]));
  const validEdges = edges.filter((edge) => nodeSet.has(edge.source) && nodeSet.has(edge.target));
  for (const edge of validEdges) {
    adjacency.get(edge.source)?.add(edge.target);
    adjacency.get(edge.target)?.add(edge.source);
  }

  const visited = new Set<string>();
  const components: Array<{ nodeIds: string[]; edges: LayoutEdge[] }> = [];
  for (const startId of nodeIds) {
    if (visited.has(startId)) continue;
    const stack = [startId];
    const componentNodeIds: string[] = [];
    visited.add(startId);
    while (stack.length) {
      const nodeId = stack.pop();
      if (!nodeId) continue;
      componentNodeIds.push(nodeId);
      const neighbors = [...(adjacency.get(nodeId) || [])].sort(compareIds).reverse();
      for (const neighborId of neighbors) {
        if (visited.has(neighborId)) continue;
        visited.add(neighborId);
        stack.push(neighborId);
      }
    }
    componentNodeIds.sort(compareIds);
    const componentSet = new Set(componentNodeIds);
    components.push({
      nodeIds: componentNodeIds,
      edges: validEdges.filter((edge) => componentSet.has(edge.source) && componentSet.has(edge.target)),
    });
  }
  return components.sort((left, right) => right.nodeIds.length - left.nodeIds.length
    || compareIds(left.nodeIds[0] || "", right.nodeIds[0] || ""));
}

export function layoutServiceGraph(nodes: LayoutNode[], edges: LayoutEdge[]): Record<string, Position> {
  const positions: Record<string, Position> = {};
  const components = findWeakComponents(nodes, edges);
  let componentY = 100;

  for (const component of components) {
    const layout = componentLayout(component.nodeIds, component.edges);
    for (const [nodeId, position] of Object.entries(layout.positions)) {
      positions[nodeId] = { x: position.x, y: position.y + componentY };
    }
    componentY += layout.height + COMPONENT_GAP;
  }

  return positions;
}
