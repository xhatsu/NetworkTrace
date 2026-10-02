// Shared visual language for learned-vs-observed relationships (Sankey, matrix, topology).
// State is always carried by fill/stroke pattern AND a glyph, never colour alone.

export type AccessState = "established" | "emerging" | "dormant" | "deviating" | "new" | "ghost";

export type StateStyle = {
  color: string;
  dash: string | undefined;   // stroke-dasharray for ribbons/edges
  fillOpacity: number;
  strokeOpacity: number;
  glyph: string;              // text marker that repeats the state without colour
  rank: number;
};

export const STATE_STYLE: Record<AccessState, StateStyle> = {
  established: { color: "var(--state-good)", dash: undefined, fillOpacity: 0.25, strokeOpacity: 0.8, glyph: "", rank: 2 },
  emerging: { color: "var(--state-learning)", dash: "4 3", fillOpacity: 0.15, strokeOpacity: 0.85, glyph: "◌", rank: 3 },
  dormant: { color: "var(--muted)", dash: "2 3", fillOpacity: 0.1, strokeOpacity: 0.6, glyph: "z", rank: 1 },
  new: { color: "var(--state-new)", dash: "3 2", fillOpacity: 0.25, strokeOpacity: 1, glyph: "+", rank: 4 },
  deviating: { color: "var(--state-bad)", dash: undefined, fillOpacity: 0.35, strokeOpacity: 1, glyph: "!", rank: 5 },
  ghost: { color: "var(--faint)", dash: "1 3", fillOpacity: 0.05, strokeOpacity: 0.75, glyph: "○", rank: 0 },
};

export const STATE_STYLE_LIGHT = STATE_STYLE;

export function getStateStyle(state: AccessState, _legacyTheme?: boolean): StateStyle {
  return STATE_STYLE[state] || STATE_STYLE.established;
}

export const STATE_ORDER: AccessState[] = ["established", "emerging", "new", "deviating", "ghost"];

export function asState(value: string | undefined | null): AccessState {
  return value && value in STATE_STYLE ? (value as AccessState) : "established";
}

export function stateShortLabel(t: (en: string, vi?: string) => string, state: AccessState): string {
  switch (state) {
    case "established": return t("Established", "Ổn định");
    case "emerging": return t("Learning", "Đang học");
    case "dormant": return t("Dormant", "Ngủ");
    case "new": return t("New", "Mới");
    case "deviating": return t("Deviating", "Lệch chuẩn");
    case "ghost": return t("Missing now", "Vắng hiện tại");
  }
}

export function stateLabel(t: (en: string, vi?: string) => string, state: AccessState): string {
  switch (state) {
    case "established": return t("Established", "Đã ổn định");
    case "emerging": return t("Emerging (learning)", "Đang học");
    case "dormant": return t("Dormant", "Không hoạt động");
    case "new": return t("New (not learned)", "Mới (chưa học)");
    case "deviating": return t("Deviating", "Lệch chuẩn");
    case "ghost": return t("Learned, not observed now", "Đã học, hiện không quan sát");
  }
}

export const ENTITY_COLOR = {
  caller: "var(--entity-service)",
  service: "var(--entity-service)",
  credential: "var(--entity-user)",
  api: "var(--entity-api)",
  ip: "var(--entity-ip)",
} as const;

export const ENTITY_COLOR_LIGHT = ENTITY_COLOR;

export function getEntityColor(kind: AccessColumn, _legacyTheme?: boolean): string {
  return ENTITY_COLOR[kind] || "var(--entity-service)";
}

export type AccessColumn = keyof typeof ENTITY_COLOR;

export type AccessNode = {
  id: string;
  kind: AccessColumn;
  label: string;
  state: AccessState;
  familiarity: string;
  width_tps: number | null;
  observed_tps: number | null;
  expected_tps: number | null;
  first_seen_ms: number;
  last_seen_ms: number;
  relationships: number;
  other?: boolean;
  other_count?: number;
  group?: boolean;
  ip_count?: number;
  role?: string;
  infrastructure?: boolean;
};

export type AccessLink = {
  id: string;
  source: string;
  target: string;
  from_column: AccessColumn;
  to_column: AccessColumn;
  state: AccessState;
  familiarity: string;
  width_tps: number | null;
  observed_tps: number | null;
  expected_tps: number | null;
  first_seen_ms: number;
  last_seen_ms: number;
  relationships: number;
  volume_known: boolean;
  detail_id: string | null;
};

export type AccessFlowResponse = {
  status: "learning" | "active";
  environment: string;
  focus: { type: string; name: string };
  basis: "observed" | "baseline";
  columns: AccessColumn[];
  nodes: AccessNode[];
  links: AccessLink[];
  top: number;
  caps: Record<string, { shown: number; total: number }>;
  ip: { expanded_role: string | null; roles: { role: string; count: number; state: AccessState; infrastructure: boolean }[]; offset: number; limit: number; total: number; role_total?: number };
  as_of_ms?: number;
  window_ms?: number;
  relationships_total?: number;
};

export type AccessMatrixResponse = {
  status: "learning" | "active";
  environment: string;
  order: "similarity" | "traffic";
  basis: "observed" | "baseline";
  rows: { name: string; requests_tps: number; apis: number }[];
  cols: { name: string; requests_tps: number; credentials: number }[];
  cells: {
    row: number; col: number; state: AccessState; familiarity: string; width_tps: number;
    observed_tps: number; expected_tps: number | null; last_seen_ms: number; first_seen_ms: number; relationships: number;
  }[];
  row_total: number; col_total: number; row_offset: number; col_offset: number; row_limit: number; col_limit: number;
  similarity_capped: boolean;
  as_of_ms?: number;
};

export function ipRoleLabel(t: (en: string, vi?: string) => string, role: string): string {
  switch (role) {
    case "client": return t("Client", "Client");
    case "load_balancer": return t("Load balancer", "Load balancer");
    case "reverse_proxy": return t("Reverse proxy", "Reverse proxy");
    case "nat": return t("NAT", "NAT");
    case "infrastructure": return t("Infrastructure", "Hạ tầng");
    default: return t("Unverified peer", "Peer chưa xác minh");
  }
}
